from shared.base import BaseHandler
from shared.db.queries import OptimizedQueries


class BrewsGetHandler(BaseHandler):
    def process_authenticated_request(self):
        try:
            # Get user's brews using optimized query
            brews_data = OptimizedQueries.get_user_brews(self.user_data["id"])
            
            brews = []
            for brew_row in brews_data:
                (
                    brew_id, name, topics, delivery_time, created_at, is_active, briefings_sent, article_count
                ) = brew_row
                
                # Parse topics if it's a string (handle legacy data)
                topics_list = topics if isinstance(topics, list) else []
                
                brews.append({
                    "id": brew_id,
                    "name": name,
                    "topics": topics_list,
                    "delivery_time": str(delivery_time) if delivery_time else None,
                    "briefings_sent": briefings_sent,
                    "article_count": article_count,
                    "is_active": is_active,
                    "created_at": created_at.isoformat() if created_at else None,
                })
            
            return self.success_response({"brews": brews})
            
        except Exception:
            return self.error_response(500, "Failed to retrieve brews")


def handler(event, context):
    return BrewsGetHandler(event, context).handle_auth_required()


# Keep lambda_handler for compatibility
lambda_handler = handler
