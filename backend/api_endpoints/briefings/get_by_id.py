from shared.base import BaseHandler
from shared.db.queries import OptimizedQueries, get_curator_log


class BriefingByIdHandler(BaseHandler):
    def process_authenticated_request(self):
        # Get run_id from path
        run_id, error = self.get_path_param("id")
        if error:
            return error
        
        # Validate ownership
        error = self.validate_ownership_required("briefing", run_id)
        if error:
            return error
        
        # Get query options
        include_content, _ = self.get_query_param("include_content", "false")
        include_articles, _ = self.get_query_param("include_articles", "false")
        include_content = include_content.lower() == "true"
        include_articles = include_articles.lower() == "true"
        
        try:
            # Get briefing data using optimized query
            briefing_data = OptimizedQueries.get_briefing_by_id(self.user_data["id"], run_id)
            if not briefing_data:
                return self.error_response(404, "Briefing not found")
            
            (
                run_id, brew_id, editorial_content, email_sent, email_sent_time, created_at,
                email, first_name, last_name, delivery_time, last_sent_date
            ) = briefing_data
            
            # Build response
            subject_line = editorial_content.get("subject", "") if editorial_content else ""
            article_count = len(editorial_content.get("articles", [])) if editorial_content else 0
            user_name = f"{first_name} {last_name}" if first_name and last_name else first_name or "User"
            
            briefing = {
                "id": run_id,
                "run_id": run_id,
                "brew_id": brew_id,
                "user_id": self.user_data["id"],
                "status": "sent" if email_sent else "pending",
                "subject": subject_line,
                "article_count": article_count,
                "created_at": created_at.isoformat() if created_at else None,
                "sent_at": email_sent_time.isoformat() if email_sent_time else None,
                "email_sent": email_sent,
                "user_info": {
                    "id": self.user_data["id"],
                    "email": email,
                    "name": user_name,
                },
                "brew_info": {
                    "id": brew_id,
                    "delivery_time": str(delivery_time) if delivery_time else None,
                    "last_sent_date": last_sent_date.isoformat() if last_sent_date else None,
                },
            }
            
            if include_content and editorial_content:
                briefing["editor_draft"] = editorial_content
            
            if include_articles:
                curator_log = get_curator_log(run_id)
                articles = curator_log.get("raw_articles") if curator_log else None

                if articles:
                    for i, article in enumerate(articles):
                        article["position"] = i + 1
                    briefing["articles"] = articles
                else:
                    briefing["articles"] = []
            
            return self.success_response(briefing)
            
        except Exception:
            return self.error_response(500, "Failed to retrieve briefing")


def lambda_handler(event, context):
    return BriefingByIdHandler(event, context).handle_auth_required()
