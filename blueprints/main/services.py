from models.user import User

class MainService:
    """
    Service class handling dashboard calculations and metrics retrieval.
    Encapsulates database operations without request dependencies.
    """
    
    @staticmethod
    def get_dashboard_metrics():
        """
        Queries actual database tables for workforce or system counts.
        Returns zero values or clean structures if database is empty.
        """
        try:
            # Gather user counts directly from DB
            total_users = User.query.count()
            active_users = User.query.filter_by(is_active=True).count()
        except Exception:
            # Fallback if migrations have not run yet
            total_users = 0
            active_users = 0

        # Return real dynamic counts
        return {
            "total_users": total_users,
            "active_users": active_users,
            "system_status": "Operational",
            "active_modules": ["Core", "Access Management"]
        }
