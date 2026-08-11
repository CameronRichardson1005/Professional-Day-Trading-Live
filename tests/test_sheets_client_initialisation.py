import trading_bot.sheets_client as sheets_module


def test_initialisation_uses_timeout_and_spreadsheet_id(
        monkeypatch,
):
    events = []

    credentials_sentinel = object()
    spreadsheet_sentinel = object()

    class FakeCredentials:
        @staticmethod
        def from_service_account_file(
                filename,
                scopes,
        ):
            events.append(
                (
                    "credentials",
                    filename,
                    scopes,
                )
            )
            return credentials_sentinel

    class FakeGoogleClient:
        def set_timeout(self, timeout):
            events.append(
                ("timeout", timeout)
            )

        def open_by_key(self, spreadsheet_id):
            events.append(
                (
                    "open_by_key",
                    spreadsheet_id,
                )
            )
            return spreadsheet_sentinel

    google_client = FakeGoogleClient()

    monkeypatch.setattr(
        sheets_module,
        "Credentials",
        FakeCredentials,
    )
    monkeypatch.setattr(
        sheets_module.gspread,
        "authorize",
        lambda credentials: (
            events.append(
                ("authorize", credentials)
            )
            or google_client
        ),
    )

    sheets = sheets_module.SheetsClient()

    assert sheets.credentials is credentials_sentinel
    assert sheets.google_client is google_client
    assert sheets.spreadsheet is spreadsheet_sentinel

    assert events == [
        (
            "credentials",
            sheets_module.CREDS_FILE,
            sheets_module.SCOPES,
        ),
        (
            "authorize",
            credentials_sentinel,
        ),
        (
            "timeout",
            sheets_module.SHEETS_REQUEST_TIMEOUT,
        ),
        (
            "open_by_key",
            sheets_module.SPREADSHEET_ID,
        ),
    ]
