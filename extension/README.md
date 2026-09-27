# Applination browser extension

The Chrome extension recognizes an open job application form and its job description. Opening the popup scans the page; it does not spend an AI call. **Autofill application** starts a tailored resume run using the current page, shows the result in the popup, and then fills the form with profile details, saved answers, drafted answers, and generated documents. The resume can be downloaded or opened in Applination's full application view. The run continues if the popup closes and resumes when it is reopened.

## Install

1. Sign in to Applination and open **Extension** in the Setup menu.
2. Download and extract the extension ZIP. Keep the extracted folder in a permanent location.
3. Open `chrome://extensions`, enable **Developer mode**, select **Load unpacked**, and choose the extracted folder containing `manifest.json`.
4. Pin Applination. Choose **Connect account** and approve the pairing code on the website.
5. Open a job application page, open the extension, and choose **Autofill application**. Review the resume and all form fields before submitting.

For development, load the repository's `extension/` folder instead of a ZIP and point the popup to `http://localhost:3000`. Apply the current Alembic migrations first. To update a manual installation, replace the extracted files and click **Reload** on `chrome://extensions`.

Edit contact details and your master resume on the Applination website. The **Application profile** page holds recurring form details and saved answers. The extension popup does not edit profile data.

The extension can read HTTP/HTTPS pages to find forms. Its revocable credential stays in Chrome's trusted extension storage; the content script does not receive the credential or AI provider keys. Connections expire after 90 days and can be revoked on the website.

The page shows a small progress panel while autofill checks fields one at a time. It picks matching options in native selects, radio buttons, checkboxes, and accessible dropdowns, and leaves choices it cannot match for review. You can stop or rerun autofill from the panel. Text fields and file inputs are also supported. Some application sites use custom widgets, inaccessible frames, or upload controls that require site-specific handling. Always review the site's form and confirm the uploaded file before submitting. Submission tracking observes recognized confirmation pages after autofill, and the popup also offers a manual **I submitted this application** action.
