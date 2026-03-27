"""ORCID OAuth 2.0 integration service."""
import httpx
import secrets
import config
from typing import Optional, Dict, Any

class ORCIDService:
    """Service for handling ORCID OAuth authentication."""

    def __init__(self):
        self.client_id = config.ORCID_CLIENT_ID
        self.client_secret = config.ORCID_CLIENT_SECRET
        self.redirect_uri = config.ORCID_REDIRECT_URI
        self.auth_url = config.ORCID_AUTH_URL
        self.token_url = config.ORCID_TOKEN_URL
        self.api_url = config.ORCID_API_URL

    def generate_state(self) -> str:
        """Generate a random state for CSRF protection."""
        return secrets.token_urlsafe(32)

    def get_authorization_url(self, state: str) -> str:
        """Generate the ORCID authorization URL."""
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "scope": "/authenticate",
            "redirect_uri": self.redirect_uri,
            "state": state
        }

        # Build URL manually to ensure proper encoding
        param_str = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"{self.auth_url}?{param_str}"

    async def exchange_code_for_token(self, code: str) -> Optional[Dict[str, Any]]:
        """Exchange authorization code for access token."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.token_url,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": self.redirect_uri
                    },
                    headers={
                        "Accept": "application/json"
                    }
                )

                if response.status_code == 200:
                    return response.json()
                else:
                    print(f"Token exchange failed: {response.status_code} - {response.text}")
                    return None
        except Exception as e:
            print(f"Error exchanging code for token: {e}")
            return None

    async def get_user_info(self, orcid_id: str, access_token: str) -> Optional[Dict[str, Any]]:
        """Fetch user information from ORCID API."""
        try:
            async with httpx.AsyncClient() as client:
                # Get person record
                response = await client.get(
                    f"{self.api_url}/{orcid_id}/person",
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {access_token}"
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    return self._parse_user_data(orcid_id, data)
                else:
                    print(f"Failed to fetch user info: {response.status_code}")
                    return None
        except Exception as e:
            print(f"Error fetching user info: {e}")
            return None

    def _parse_user_data(self, orcid_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse ORCID API response to extract user information."""
        user_info = {
            "orcid_id": orcid_id,
            "name": None,
            "email": None,
            "emails_list": [],  # All emails with verified flags
            "affiliation": None
        }

        # Extract name
        if "name" in data:
            name_data = data["name"]
            given_name = name_data.get("given-names", {}).get("value", "")
            family_name = name_data.get("family-name", {}).get("value", "")
            user_info["name"] = f"{given_name} {family_name}".strip()

            if not user_info["name"]:
                user_info["name"] = orcid_id  # Fallback to ORCID ID

        # Extract all emails
        if "emails" in data and "email" in data["emails"]:
            emails = data["emails"]["email"]
            if emails:
                for email_entry in emails:
                    addr = email_entry.get("email")
                    if addr:
                        user_info["emails_list"].append({
                            "email": addr,
                            "verified": bool(email_entry.get("verified", False)),
                            "primary": bool(email_entry.get("primary", False)),
                        })

                # Pick best single email for backwards compat (users.email cache)
                for entry in user_info["emails_list"]:
                    if entry["verified"] or entry["primary"]:
                        user_info["email"] = entry["email"]
                        break
                if not user_info["email"] and user_info["emails_list"]:
                    user_info["email"] = user_info["emails_list"][0]["email"]

        # Extract affiliation (first employment)
        if "employments" in data and "affiliation-group" in data["employments"]:
            groups = data["employments"]["affiliation-group"]
            if groups:
                summaries = groups[0].get("summaries", [])
                if summaries:
                    employment = summaries[0].get("employment-summary", {})
                    org = employment.get("organization", {})
                    user_info["affiliation"] = org.get("name")

        return user_info

    async def get_works_count(self, orcid_id: str) -> int:
        """Get total count of journal articles, conference papers, books, and book chapters from ORCID.

        Only counts:
        - journal-article
        - conference-paper
        - book
        - book-chapter

        Excludes: datasets, peer reviews, other contributions, etc.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.api_url}/{orcid_id}/works",
                    headers={"Accept": "application/json"}
                )

                if response.status_code == 200:
                    data = response.json()
                    groups = data.get("group", [])

                    # Valid work types for badge calculation
                    valid_types = {
                        'journal-article',
                        'conference-paper',
                        'book',
                        'book-chapter'
                    }

                    count = 0
                    for group in groups:
                        summaries = group.get("work-summary", [])
                        if not summaries:
                            continue

                        summary = summaries[0]  # Take first summary
                        work_type = summary.get("type", "").lower()

                        # Count only valid publication types
                        if work_type in valid_types:
                            count += 1

                    print(f"ORCID {orcid_id}: Found {count} valid works")
                    return count
                else:
                    print(f"Failed to fetch works: {response.status_code}")
                    return 0
        except Exception as e:
            print(f"Error fetching works count: {e}")
            return 0

    def calculate_badge(self, works_count: int) -> str:
        """Calculate badge level based on works count.

        Badge levels:
        - gold: 50+ works
        - silver: 25-49 works
        - bronze: 6-24 works
        - copper: 1-5 works
        - new: 0 works (completely new researchers)
        """
        if works_count >= 50:
            return "gold"
        elif works_count >= 25:
            return "silver"
        elif works_count >= 6:
            return "bronze"
        elif works_count >= 1:
            return "copper"
        else:
            return "new"

    async def get_journal_articles(self, orcid_id: str, limit: int = 5) -> list:
        """Get latest journal articles and books from ORCID.

        Returns a list of journal articles and books with full details including:
        - title
        - journal (or publisher for books)
        - year
        - doi
        - url
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.api_url}/{orcid_id}/works",
                    headers={"Accept": "application/json"}
                )

                if response.status_code != 200:
                    print(f"Failed to fetch works: {response.status_code}")
                    return []

                data = response.json()
                groups = data.get("group", [])

                journal_articles = []

                for group in groups:
                    summaries = group.get("work-summary", [])
                    if not summaries:
                        continue

                    summary = summaries[0]  # Take first summary
                    work_type = summary.get("type", "").lower()

                    # Filter for journal articles and books
                    if "journal" in work_type or "book" in work_type:
                        title_data = summary.get("title", {})
                        title = title_data.get("title", {}).get("value", "Untitled")

                        journal = summary.get("journal-title", {}).get("value", "Unknown Journal")

                        # Get year
                        pub_date = summary.get("publication-date")
                        year = None
                        if pub_date:
                            year = pub_date.get("year", {}).get("value")

                        # Get DOI and URL
                        doi = None
                        url = None
                        external_ids = summary.get("external-ids", {}).get("external-id", [])
                        for ext_id in external_ids:
                            if ext_id.get("external-id-type") == "doi":
                                doi = ext_id.get("external-id-value")
                                url = f"https://doi.org/{doi}"
                                break

                        journal_articles.append({
                            "title": title,
                            "journal": journal,
                            "year": year,
                            "doi": doi,
                            "url": url
                        })

                # Sort by year (most recent first)
                journal_articles.sort(key=lambda x: x.get("year") or 0, reverse=True)

                # Return limited results
                return journal_articles[:limit]

        except Exception as e:
            print(f"Error fetching journal articles: {e}")
            return []

    async def update_user_badge(self, orcid_id: str) -> dict:
        """Update user badge and works data.

        Returns:
        - works_count: int
        - badge: str
        - journal_articles: list
        """
        works_count = await self.get_works_count(orcid_id)
        badge = self.calculate_badge(works_count)
        journal_articles = await self.get_journal_articles(orcid_id, limit=5)

        return {
            "works_count": works_count,
            "badge": badge,
            "journal_articles": journal_articles
        }

# Create singleton instance
orcid_service = ORCIDService()
