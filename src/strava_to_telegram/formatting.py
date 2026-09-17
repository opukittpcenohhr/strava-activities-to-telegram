"""Activity message rendering and content fingerprints."""
import hashlib

from .strava import Activity


def render(activity: Activity) -> str:
    seconds = int(activity.moving_time or 0)
    distance = float(activity.distance or 0) / 1000
    local_date = activity.start_date_local
    date_text = local_date.date().isoformat() if local_date else ''
    sport = activity.sport_type or activity.type or 'Activity'
    return (f"{str(activity.name or 'Activity')[:250]}\n"
            f"{sport} · {date_text}\n"
            f"{distance:.2f} km · {seconds // 3600}:{seconds // 60 % 60:02}:{seconds % 60:02}\n"
            f"https://www.strava.com/activities/{activity.id}")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
