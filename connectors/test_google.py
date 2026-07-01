from connectors.google_tools import get_recent_emails

emails = get_recent_emails(5)
for e in emails:
    print(e["date"], "|", e["from"], "|", e["subject"])