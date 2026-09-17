"""Distance, duration and effort, formatted the way a summary reads."""

# Pace (min/km) reads naturally on foot; speed (km/h) reads naturally on wheels.
PACED = {'Run', 'VirtualRun', 'TrailRun', 'Walk', 'Hike', 'Swim'}


def distance(km: float) -> str:
    return f'{km:.2f} km'


def duration(seconds: int) -> str:
    """Hours and minutes only: seconds are noise at the length of an activity."""
    hours, minutes = divmod(round(seconds / 60), 60)
    return f'{hours}h {minutes:02}m' if hours else f'{minutes}m'


def effort(sport: str, km: float, seconds: int) -> str | None:
    """Pace or speed, whichever suits the sport, or None when it cannot be derived."""
    if km <= 0 or seconds <= 0:
        return None
    if sport in PACED:
        pace = seconds / 60 / km
        return f'{int(pace)}:{round((pace % 1) * 60):02} /km'
    return f'{km / (seconds / 3600):.1f} km/h'
