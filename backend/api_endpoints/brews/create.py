from shared.base import BaseHandler
from shared.db.queries import OptimizedQueries
from shared.utils.other_utils import normalize_delivery_time


class BrewsCreateHandler(BaseHandler):
    def process_authenticated_request(self):
        # Parse request body
        body, error = self.parse_body()
        if error:
            return error
        
        # Validate required fields
        if not isinstance(body, dict):
            return self.error_response(400, "Request body must be an object")
        name = body.get("name", "")
        topics = body.get("topics", [])
        delivery_time = body.get("delivery_time", "")
        article_count = body.get("article_count", 5)
        if not isinstance(name, str) or not isinstance(delivery_time, str):
            return self.error_response(400, "Name and delivery time must be strings")
        name, delivery_time = name.strip(), delivery_time.strip()
        if type(article_count) is not int or not 1 <= article_count <= 10:
            return self.error_response(400, "Article count must be an integer from 1 to 10")
        
        if not name:
            return self.error_response(400, "Brew name is required")
        if not delivery_time:
            return self.error_response(400, "Delivery time is required")
        # Store a canonical HH:MM:SS (the client sends HH:MM); the curator and
        # scheduler both parse this strictly.
        try:
            delivery_time = normalize_delivery_time(delivery_time)
        except ValueError:
            return self.error_response(400, "Delivery time must be in HH:MM or HH:MM:SS format")
        if not topics or not isinstance(topics, list):
            return self.error_response(400, "Topics must be a non-empty array")
        
        # Validate name length
        if len(name) > 255:
            return self.error_response(400, "Brew name too long")
        
        # Validate topics
        if len(topics) > 10:
            return self.error_response(400, "Maximum 10 topics allowed")

        # Validate each topic is a non-empty string <= 100 chars (and strip it)
        cleaned_topics = []
        for topic in topics:
            if not isinstance(topic, str) or not topic.strip():
                return self.error_response(400, "Each topic must be a non-empty string")
            stripped = topic.strip()
            if len(stripped) > 100:
                return self.error_response(400, "Each topic must be at most 100 characters")
            cleaned_topics.append(stripped)
        topics = cleaned_topics

        try:
            # Create brew using optimized query
            brew_id = OptimizedQueries.create_brew(
                self.user_data["id"], name, topics, delivery_time, article_count
            )
            
            return self.success_response({
                "message": "Brew created successfully",
                "brew_id": str(brew_id),
                "name": name,
                "topics": topics,
                "delivery_time": delivery_time,
                "article_count": article_count,
            })
            
        except Exception:
            return self.error_response(500, "Failed to create brew")


def handler(event, context):
    return BrewsCreateHandler(event, context).handle_auth_required()


# Keep lambda_handler for compatibility
lambda_handler = handler
