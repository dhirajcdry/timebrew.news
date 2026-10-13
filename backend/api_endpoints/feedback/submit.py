from shared.base import BaseHandler
from shared.db.queries import OptimizedQueries, get_editor_log_by_editorial_id
import traceback


class FeedbackSubmitHandler(BaseHandler):
    def process_authenticated_request(self):
        try:
            print(f"[FEEDBACK] Starting feedback submission for user_id: {self.user_data['id']}")
            
            # Parse request body
            print(f"[FEEDBACK] Parsing request body: {self.event.get('body')}")
            body, error = self.parse_body()
            if error:
                print(f"[FEEDBACK] ERROR: Failed to parse request body: {self.event.get('body')}")
                return error
            
            print(f"[FEEDBACK] Request body parsed successfully. Keys: {list(body.keys()) if body else []}")
            
        except Exception as e:
            print(f"[FEEDBACK] ERROR: Unexpected error in request initialization: {str(e)}")
            print(f"[FEEDBACK] ERROR: Traceback: {traceback.format_exc()}")
            return self.error_response(500, "Internal server error during request initialization")
        
        try:
            # Extract and validate required fields
            editorial_id = body.get("editorial_id")
            feedback_type = body.get("feedback_type")  # "overall" or "article"
            like = body.get("like")  # boolean
            
            print(f"[FEEDBACK] Extracted fields - editorial_id: {editorial_id}, feedback_type: {feedback_type}, like: {like}")
            
            if not all([editorial_id, feedback_type, like is not None]):
                print(f"[FEEDBACK] ERROR: Missing required fields - editorial_id: {editorial_id}, feedback_type: {feedback_type}, like: {like}")
                return self.error_response(400, "editorial_id, feedback_type, and like are required")
            
            if feedback_type not in ["overall", "article"]:
                print(f"[FEEDBACK] ERROR: Invalid feedback_type: {feedback_type}")
                return self.error_response(400, 'feedback_type must be "overall" or "article"')
            
            if not isinstance(like, bool):
                print(f"[FEEDBACK] ERROR: Invalid like value type - like: {like}, type: {type(like).__name__}")
                return self.error_response(400, "like must be a boolean")
                
        except Exception as e:
            print(f"[FEEDBACK] ERROR: Error during field validation: {str(e)}")
            print(f"[FEEDBACK] ERROR: Traceback: {traceback.format_exc()}")
            return self.error_response(500, "Internal server error during field validation")
        
        try:
            # Validate ownership of editorial content
            print(f"[FEEDBACK] Validating editorial ownership for editorial_id: {editorial_id}")
            error = self.validate_ownership_required("editorial", editorial_id)
            if error:
                print(f"[FEEDBACK] ERROR: Editorial ownership validation failed for editorial_id: {editorial_id}")
                return error
            print(f"[FEEDBACK] Editorial ownership validated successfully for editorial_id: {editorial_id}")
            
        except Exception as e:
            print(f"[FEEDBACK] ERROR: Error during ownership validation: {str(e)}")
            print(f"[FEEDBACK] ERROR: Traceback: {traceback.format_exc()}")
            return self.error_response(500, "Internal server error during ownership validation")
        
        # Convert boolean to feedback type
        feedback_value = "like" if like else "dislike"
        print(f"[FEEDBACK] Converted feedback value - like: {like} -> feedback_value: {feedback_value}")
        
        try:
            if feedback_type == "overall":
                # Overall briefing feedback - all article fields NULL
                print(f"[FEEDBACK] Submitting overall feedback - user_id: {self.user_data['id']}, editorial_id: {editorial_id}, feedback_value: {feedback_value}")
                
                feedback_id, action = OptimizedQueries.submit_feedback(
                    user_id=self.user_data["id"],
                    editorial_id=editorial_id,
                    feedback_type=feedback_value,
                    article_position=None,
                    source_url=None,
                    article_title=None,
                    article_source=None
                )
                
                print(f"[FEEDBACK] Overall feedback submitted successfully - feedback_id: {feedback_id}, action: {action}")
                
            elif feedback_type == "article":
                # Article feedback - get article details from request
                article_position = body.get("article_position")
                # Resolve article identity from the owned saved briefing. Client
                # supplied titles/URLs are not reliable personalization evidence.
                article_data = {}
                
                print(f"[FEEDBACK] Processing article feedback - article_position: {article_position}, article_data_keys: {list(article_data.keys()) if article_data else []}")
                
                if article_position is None:
                    print(f"[FEEDBACK] ERROR: Missing article_position for article feedback")
                    return self.error_response(400, "article_position is required for article feedback")
                
                try:
                    if type(article_position) is not int or article_position < 0:
                        raise ValueError("Article position cannot be negative")
                    print(f"[FEEDBACK] Article position validated: {article_position}")
                except (ValueError, TypeError) as e:
                    print(f"[FEEDBACK] ERROR: Invalid article_position: {article_position}, error: {str(e)}")
                    return self.error_response(400, "article_position must be a non-negative integer")

                editorial = get_editor_log_by_editorial_id(editorial_id)
                content = (editorial or {}).get("editorial_content") or {}
                articles = content.get("articles", [])
                if article_position >= len(articles):
                    return self.error_response(400, "Article position is outside this briefing")
                article_data = articles[article_position]
                
                print(f"[FEEDBACK] Submitting article feedback - user_id: {self.user_data['id']}, editorial_id: {editorial_id}, feedback_value: {feedback_value}, article_position: {article_position}")
                print(f"[FEEDBACK] Article data - source_url: {article_data.get('original_url')}, title: {article_data.get('headline')}, source: {article_data.get('source')}")
                
                feedback_id, action = OptimizedQueries.submit_feedback(
                    user_id=self.user_data["id"],
                    editorial_id=editorial_id,
                    feedback_type=feedback_value,
                    article_position=article_position,
                    source_url=article_data.get("original_url"),
                    article_title=article_data.get("headline"),
                    article_source=article_data.get("source")
                )
                
                print(f"[FEEDBACK] Article feedback submitted successfully - feedback_id: {feedback_id}, action: {action}")
            
            response_data = {
                "message": f"Feedback {action} successfully",
                "feedback_id": feedback_id,
                "editorial_id": editorial_id,
                "feedback_type": feedback_type,
                "like": like,
                "action": action,
            }
            
            print(f"[FEEDBACK] Feedback submission completed successfully: {response_data}")
            
            return self.success_response(response_data)
            
        except Exception as e:
            print(f"[FEEDBACK] ERROR: Failed to submit feedback - database error: {str(e)}")
            print(f"[FEEDBACK] ERROR: user_id: {self.user_data['id']}, editorial_id: {editorial_id}, feedback_type: {feedback_type}")
            print(f"[FEEDBACK] ERROR: Traceback: {traceback.format_exc()}")
            return self.error_response(500, "Failed to submit feedback")


def lambda_handler(event, context):
    return FeedbackSubmitHandler(event, context).handle_auth_required()
