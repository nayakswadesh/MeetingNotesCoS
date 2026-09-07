# Connect Google

1. In Google Cloud, create or select a project, enable **Google Calendar API** and **Gmail API**, and configure the OAuth consent screen. Add `nayakswadesh@gmail.com` as a test user if the app is external and still in testing.
2. Create an OAuth client of type **Desktop app**, download its JSON, and save it in this project as `google-client-secret.json`.
3. From this project directory, run:

   ```powershell
   .\.venv\Scripts\python.exe -m src.connect_google
   ```

4. Sign in as `nayakswadesh@gmail.com` in the browser and approve Gmail send, Gmail metadata (used only to confirm the signed-in address), and Calendar event permissions. The command confirms the connected account and creates the ignored `google-token.json` refresh token.

If you previously connected the account before adding a scope, delete the ignored
`google-token.json` file and run the command again. A saved OAuth token cannot be
expanded with additional permissions without reauthorizing in the browser.

After that, pressing **Approve & Send** in Telegram sends the email from that account and creates the event in its primary calendar. The program refuses to send if a different Google account is connected.
