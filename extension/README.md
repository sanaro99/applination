# Applination Autofill extension

This is a Chrome Manifest V3 extension. It fills standard job application form controls from an Applination profile, inserts saved answers, drafts new answers with the account's configured AI provider, attaches selected PDF/DOCX documents, and tracks confirmed submissions.

## Install as an early tester

1. Sign in to Applination and open **Extension** in the Setup menu.
2. Download the extension ZIP and extract it. Keep the extracted `applination-extension` folder in a permanent location.
3. Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**, and select the extracted folder containing `manifest.json`.
4. Pin Applination Autofill, open its popup, and choose **Connect account**. Approve the pairing code on the Applination page that opens.
5. To update, download the new ZIP, replace the contents of the same extracted folder, and click **Reload** on `chrome://extensions`.

The website downloads a ZIP assembled from the runtime extension files on the hosted backend. Manual installations do not update automatically.

## Install for development

1. Start Applination and run the latest Alembic migration (`alembic upgrade head`).
2. Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**, and select this `extension/` folder.
3. Pin the extension. Open its popup, set the Applination URL (the hosted URL by default, or `http://localhost:3000` for local development), and choose **Connect account**.
4. Sign in to Applination in the tab that opens and approve the displayed code. Reopen the extension popup if it closed; the pending connection is retained for five minutes.
5. On a job application page, check the detected company and role, choose documents, then select **Fill this page and attach selected documents**. Review every field and file before submitting.

The extension has access to HTTP/HTTPS pages so it can recognize application forms and their confirmation pages across job sites. It stores a revocable extension credential in Chrome's local extension storage; the content script never receives the credential or an AI provider key. Connections expire after 90 days and can be revoked from **Browser extension** in Applination.

## Current behavior and limits

- Standard native text inputs, select menus, radio controls, and file inputs are supported. Job sites with custom widgets may need site-specific adapters.
- Contact details and explicitly saved application answers fill directly; the first education entry and most recent employer can fill when the form asks for those specifically. Repeating work-history sections still need site-specific support.
- Saved answers are reused only for the same normalized question text. **Fill this page** can draft and insert up to ten unanswered essay fields when its AI checkbox is enabled. Drafts remain editable and are saved to the answer bank only when you choose **Insert and save answer**.
- The extension observes a submission only after **Fill this page** has armed tracking for that tab. It marks a job applied after recognizing a confirmation page. If a site does not show a recognizable confirmation, use **I submitted this application**.
- File fields must be identifiable as a resume or cover letter. If a site uses an unsupported upload control, attach the document manually. Always check that the site accepted the file.
- Browser and application site restrictions can prevent an extension from running on some pages.

The source is plain JavaScript and CSS; no build step is required for the unpacked extension.
