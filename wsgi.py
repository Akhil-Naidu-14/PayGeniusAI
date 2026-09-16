from app import create_app

# Instantiate the Flask application factory
app = create_app()

if __name__ == "__main__":
    app.run()
