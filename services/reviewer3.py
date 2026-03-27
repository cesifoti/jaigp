"""Service for reviewer3.com AI review integration.

Reviewer3 API endpoints (base: https://reviewer3.com):
  - GET  /api/internal/user?email=...          Check if user exists
  - POST /api/internal/user                    Create user {email, name}
  - POST /api/internal/review                  Submit PDF (multipart/form-data, fire-and-forget)
  - GET  /api/internal/review/{sessionId}      Poll for review results

Auth: x-api-key header with sk_... key.
Reviews are displayed on JAIGP directly (sendEmail=false).
"""
import httpx
import config


class Reviewer3Service:
    """Service for reviewer3.com API."""

    def __init__(self):
        self.base_url = config.REVIEWER3_API_URL.rstrip("/")
        self.api_key = config.REVIEWER3_API_KEY

    @property
    def _headers(self):
        return {"x-api-key": self.api_key}

    async def ensure_user(self, email: str, name: str) -> str:
        """Check if user exists on Reviewer3, create if needed.

        Returns the Reviewer3 user ID (e.g. 'usr_abc123').
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Check if user exists
            resp = await client.get(
                f"{self.base_url}/api/internal/user",
                params={"email": email},
                headers=self._headers,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("exists"):
                return data["user"]["id"]

            # Create user
            resp = await client.post(
                f"{self.base_url}/api/internal/user",
                json={"email": email, "name": name},
                headers=self._headers,
            )

            # Handle race condition: user created between check and create
            if resp.status_code == 409:
                resp = await client.get(
                    f"{self.base_url}/api/internal/user",
                    params={"email": email},
                    headers=self._headers,
                )
                resp.raise_for_status()
                return resp.json()["user"]["id"]

            resp.raise_for_status()
            return resp.json()["user"]["id"]

    async def submit_paper(
        self,
        pdf_path: str,
        reviewer3_user_id: str,
        title: str,
        filename: str = None,
        review_mode: str = "journal",
    ) -> dict:
        """Submit a paper PDF for AI review.

        This is fire-and-forget — the review runs asynchronously on Reviewer3's end.
        Email notifications are disabled; reviews are displayed on JAIGP directly.

        Args:
            pdf_path: Path to the PDF file on disk.
            reviewer3_user_id: The Reviewer3 user ID who owns this review.
            title: Manuscript title.
            filename: Display filename (defaults to file name).
            review_mode: 'author' (3 reviewers), 'journal' (6+ reviewers), or 'cvpr'.

        Returns:
            dict with {success, sessionId}
        """
        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(pdf_path, "rb") as f:
                files = {"file": (filename or "manuscript.pdf", f, "application/pdf")}
                data = {
                    "userId": reviewer3_user_id,
                    "title": title,
                    "reviewMode": review_mode,
                    "sendEmail": "false",
                }
                if filename:
                    data["filename"] = filename

                resp = await client.post(
                    f"{self.base_url}/api/internal/review",
                    files=files,
                    data=data,
                    headers=self._headers,
                )

            resp.raise_for_status()
            return resp.json()

    async def revise_paper(
        self,
        session_id: str,
        revised_pdf_path: str,
        author_response_text: str,
    ) -> dict:
        """Submit a revised manuscript for synchronous scoring via /revise.

        Blocks until evaluation is complete. The review session must be 'completed'
        before calling this.

        Args:
            session_id: The original review session ID to revise against.
            revised_pdf_path: Path to the revised manuscript PDF on disk.
            author_response_text: Freeform text explaining how comments were addressed.
                                  Extracted from the author's response letter PDF.

        Returns:
            dict with {deskReject, evaluations: [{originalComment, authorResponse,
            reviewerResponse, score}]}
        """
        async with httpx.AsyncClient(timeout=300.0) as client:
            with open(revised_pdf_path, "rb") as f:
                resp = await client.post(
                    f"{self.base_url}/api/internal/review/{session_id}/revise",
                    files={"file": ("revised_manuscript.pdf", f, "application/pdf")},
                    data={"authorResponse": author_response_text},
                    headers=self._headers,
                )
            resp.raise_for_status()
            return resp.json()

    async def check_status(self, session_id: str) -> dict:
        """Check the status of an AI review.

        Returns:
            dict with {sessionId, status, comments} where status is 'pending' or 'completed'.
            When completed, comments is a list of {reviewerId, comment} dicts.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.base_url}/api/internal/review/{session_id}",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()



# Singleton
reviewer3_service = Reviewer3Service()
