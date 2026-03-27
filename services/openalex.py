"""OpenAlex API integration for field classification."""
import httpx
import config
from typing import List, Dict, Any, Optional

class OpenAlexService:
    """Service for OpenAlex API integration."""

    def __init__(self):
        self.api_url = config.OPENALEX_API_URL
        self.email = config.OPENALEX_API_EMAIL
        self.headers = {
            "User-Agent": f"JAIP (mailto:{self.email})",
            "Accept": "application/json"
        }

    async def suggest_fields(self, title: str, abstract: str = None) -> List[Dict[str, Any]]:
        """
        Suggest research fields based on paper title and abstract.
        Returns list of suggested topics/fields.
        """
        try:
            # Construct search query
            search_text = title
            if abstract:
                # Use first 200 chars of abstract
                search_text += " " + abstract[:200]

            # Search for relevant works
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.api_url}/works",
                    params={
                        "search": search_text,
                        "per_page": 5
                    },
                    headers=self.headers
                )

                if response.status_code != 200:
                    print(f"OpenAlex API error: {response.status_code}")
                    return []

                data = response.json()
                results = data.get("results", [])

                # Extract topics from results
                topics = self._extract_topics(results)

                return topics[:10]  # Return top 10 suggestions

        except Exception as e:
            print(f"Error fetching OpenAlex suggestions: {e}")
            return []

    def _extract_topics(self, results: List[Dict]) -> List[Dict[str, Any]]:
        """Extract and aggregate topics from search results."""
        topic_counts = {}

        for work in results:
            # Get topics from work
            topics = work.get("topics", [])

            for topic in topics:
                topic_id = topic.get("id", "")
                if not topic_id:
                    continue

                if topic_id not in topic_counts:
                    topic_counts[topic_id] = {
                        "field_id": topic_id.split("/")[-1] if topic_id else None,
                        "field_name": topic.get("display_name", ""),
                        "display_name": topic.get("display_name", ""),
                        "field_type": "topic",
                        "count": 0,
                        "subfield": topic.get("subfield", {}),
                        "field": topic.get("field", {}),
                        "domain": topic.get("domain", {})
                    }

                topic_counts[topic_id]["count"] += 1

        # Sort by count and return
        sorted_topics = sorted(
            topic_counts.values(),
            key=lambda x: x["count"],
            reverse=True
        )

        return sorted_topics

    async def get_topic_hierarchy(self, topic_id: str) -> Optional[Dict[str, Any]]:
        """Get full hierarchy for a topic (domain -> field -> subfield -> topic)."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.api_url}/topics/{topic_id}",
                    headers=self.headers
                )

                if response.status_code != 200:
                    return None

                topic = response.json()

                return {
                    "topic": {
                        "id": topic.get("id", "").split("/")[-1],
                        "name": topic.get("display_name", "")
                    },
                    "subfield": topic.get("subfield", {}),
                    "field": topic.get("field", {}),
                    "domain": topic.get("domain", {})
                }

        except Exception as e:
            print(f"Error fetching topic hierarchy: {e}")
            return None

# Create singleton instance
openalex_service = OpenAlexService()
