from campus_alerts.config import AppConfig
from campus_alerts.database import initialize_database
from campus_alerts.http_server import run_server


def main() -> None:
    config = AppConfig.from_environment()
    initialize_database(config.database_path)
    run_server(config)


if __name__ == "__main__":
    main()

