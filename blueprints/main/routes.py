from flask import render_template
from blueprints.main import main_bp
from blueprints.main.services import MainService

@main_bp.route("/")
def index():
    from flask_login import current_user
    print(f"DEBUG INDEX VIEW: current_user={current_user}, authenticated={current_user.is_authenticated}")
    """
    Renders the central system dashboard page.



    Renders the central system dashboard page.
    Delegates all backend data gathering to the Service layer.
    """
    # Fetch metrics from business service layer
    metrics = MainService.get_dashboard_metrics()
    
    # Delegate rendering to templates with clean context binding
    return render_template("index.html", metrics=metrics)
