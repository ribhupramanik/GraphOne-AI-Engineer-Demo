import argparse
import csv
import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.file"]
TABS = ["Startups", "Products", "Research Papers", "Jobs", "News", "Entity Mapping Log"]


def auth(credentials_json):
    token_path = Path(".google_token.json")
    creds = Credentials.from_authorized_user_file(token_path, SCOPES) if token_path.exists() else None
    if creds is None or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_json, SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
    return creds


def read_tab(name, csv_dir):
    filename = name.lower().replace(" ", "_") + ".csv"
    with (Path(csv_dir) / filename).open(encoding="utf-8-sig", newline="") as source:
        return list(csv.reader(source))


def main():
    parser = argparse.ArgumentParser(description="Publish verified CSV outputs as six Google Sheets tabs")
    parser.add_argument("--credentials", default="credentials.json")
    parser.add_argument("--csv-dir", default="output/csv")
    parser.add_argument("--title", default="GraphOne AI Engineer - Verified Data Output")
    parser.add_argument("--spreadsheet-id")
    parser.add_argument("--public", action="store_true")
    args = parser.parse_args()
    credentials = auth(args.credentials)
    sheets = build("sheets", "v4", credentials=credentials)
    if args.spreadsheet_id:
        spreadsheet_id = args.spreadsheet_id
        existing = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        existing_titles = {sheet["properties"]["title"] for sheet in existing["sheets"]}
        create_tabs = [name for name in TABS if name not in existing_titles]
        if create_tabs:
            sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": name}}} for name in create_tabs]}).execute()
    else:
        created = sheets.spreadsheets().create(body={"properties": {"title": args.title},
             "sheets": [{"properties": {"title": name}} for name in TABS]}).execute()
        spreadsheet_id = created["spreadsheetId"]
    for name in TABS:
        rows = read_tab(name, args.csv_dir)
        if not rows:
            raise ValueError(f"Missing header for {name}")
        sheet_range = "'" + name.replace("'", "''") + "'!A1"
        sheets.spreadsheets().values().clear(spreadsheetId=spreadsheet_id,
            range="'" + name.replace("'", "''") + "'", body={}).execute()
        for start in range(0, len(rows), 400):
            subset = rows[start:start + 400]
            sheets.spreadsheets().values().update(spreadsheetId=spreadsheet_id,
                range=f"'{name}'!A{start + 1}", valueInputOption="RAW",
                body={"values": subset}).execute()
    if args.public:
        drive = build("drive", "v3", credentials=credentials)
        drive.permissions().create(fileId=spreadsheet_id, body={"type": "anyone", "role": "reader"}, fields="id").execute()
    url = "https://docs.google.com/spreadsheets/d/" + spreadsheet_id + "/edit"
    print(json.dumps({"spreadsheet_url": url, "public_requested": args.public}, indent=2))


if __name__ == "__main__":
    main()
