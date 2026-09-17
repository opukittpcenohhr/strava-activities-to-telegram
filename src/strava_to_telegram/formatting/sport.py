"""Sport names and their emoji."""

import re

EMOJI = {
    'Ride': '🚴',
    'VirtualRide': '🚴',
    'EBikeRide': '🚴',
    'MountainBikeRide': '🚵',
    'GravelRide': '🚵',
    'Run': '🏃',
    'VirtualRun': '🏃',
    'TrailRun': '🏃',
    'Walk': '🚶',
    'Hike': '🥾',
    'Swim': '🏊',
    'StandUpPaddling': '🏄',
    'Surfing': '🏄',
    'Kayaking': '🛶',
    'Canoeing': '🛶',
    'Rowing': '🚣',
    'WeightTraining': '🏋️',
    'Workout': '🏋️',
    'Crossfit': '🏋️',
    'Yoga': '🧘',
    'AlpineSki': '⛷️',
    'BackcountrySki': '⛷️',
    'NordicSki': '🎿',
    'Snowboard': '🏂',
    'IceSkate': '⛸️',
    'Golf': '⛳',
    'Tennis': '🎾',
    'Soccer': '⚽',
    'Badminton': '🏸',
    'Skateboard': '🛹',
    'Elliptical': '🏃',
}
FALLBACK = '🏅'


def emoji(sport: str) -> str:
    return EMOJI.get(sport, FALLBACK)


def label(sport: str) -> str:
    """`StandUpPaddling` -> `Stand Up Paddling`, leaving plain names alone."""
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', sport)
