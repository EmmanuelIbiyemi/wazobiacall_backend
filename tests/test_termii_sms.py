import asyncio
import importlib.util
import os
import pathlib
import unittest
from unittest.mock import patch

from fastapi import HTTPException

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "apis" / "termii.py"
SPEC = importlib.util.spec_from_file_location("termii_sms", MODULE_PATH)
termii_sms = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(termii_sms)


class FakeResponse:
    def __init__(self, status_code=200, text="sent") -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise termii_sms.httpx.HTTPStatusError(
                "Termii request failed",
                request=termii_sms.httpx.Request("POST", "https://termii.test"),
                response=termii_sms.httpx.Response(self.status_code),
            )


class FakeClient:
    response = FakeResponse()
    request = None

    def __init__(self, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        self.__class__.request = (url, kwargs)
        return self.__class__.response


class TermiiSmsTests(unittest.TestCase):
    def test_sends_verification_code_with_configured_sender(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "TERMII_BASE_URL": "https://termii.test",
                    "TERMII_API_KEY": "test-key",
                    "TERMII_SENDER_ID": "Wazobia",
                },
            ),
            patch.object(termii_sms.httpx, "AsyncClient", FakeClient),
        ):
            FakeClient.response = FakeResponse(text="message sent")
            result = asyncio.run(
                termii_sms.send_verification_code("+2348012345678", "123456")
            )

        url, request = FakeClient.request
        self.assertEqual(url, "https://termii.test/api/sms/send")
        self.assertEqual(request["json"]["to"], "+2348012345678")
        self.assertEqual(request["json"]["from"], "Wazobia")
        self.assertEqual(request["json"]["api_key"], "test-key")
        self.assertIn("verification code is 123456", request["json"]["sms"])
        self.assertEqual(result, {"status": "successful", "message": "message sent"})

    def test_sends_invitation_message(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "TERMII_BASE_URL": "https://termii.test",
                    "TERMII_API_KEY": "test-key",
                    "TERMII_SENDER_ID": "Wazobia",
                },
            ),
            patch.object(termii_sms.httpx, "AsyncClient", FakeClient),
        ):
            FakeClient.response = FakeResponse()
            asyncio.run(termii_sms.send_invitation("+2348012345678", "Ada"))

        self.assertIn("Ada is trying to call you", FakeClient.request[1]["json"]["sms"])

    def test_missing_configuration_is_reported(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaises(HTTPException) as error,
        ):
            asyncio.run(
                termii_sms.send_verification_code("+2348012345678", "123456")
            )

        self.assertEqual(error.exception.status_code, 503)

    def test_termii_failure_is_not_reported_as_success(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "TERMII_BASE_URL": "https://termii.test",
                    "TERMII_API_KEY": "test-key",
                    "TERMII_SENDER_ID": "Wazobia",
                },
            ),
            patch.object(termii_sms.httpx, "AsyncClient", FakeClient),
            self.assertRaises(HTTPException) as error,
        ):
            FakeClient.response = FakeResponse(status_code=401)
            asyncio.run(
                termii_sms.send_verification_code("+2348012345678", "123456")
            )

        self.assertEqual(error.exception.status_code, 502)


if __name__ == "__main__":
    unittest.main()
