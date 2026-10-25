import random

SETTINGS = [
    "a chaotic Indian wedding where everything goes wrong", "a college exam night with zero preparation",
    "a family WhatsApp group argument that gets out of control", "an office where the boss's chair keeps disappearing",
    "a cricket match on a narrow street with a very strict neighbour", "an auto-rickshaw ride in heavy traffic",
    "a monsoon day with a leaking roof and one umbrella", "a street-food stall with a secret recipe race",
    "a landlord and tenant fighting over a tiny repair", "a work-from-home day with bad internet and a pet",
    "a first date at a restaurant with a very clumsy waiter", "a diet that starts tomorrow, every day",
    "a power cut during an important online meeting", "a train journey with a stolen window seat",
    "a village fair with a runaway goat", "a mobile phone that is lost while it is in someone's hand",
    "a cooking show where the chef cannot cook", "a sleepy night watchman and a very smart thief",
    "a gym on the first day of the year", "a school reunion where everyone lies about their success",
    "an online shopping order that arrives completely wrong", "a haunted house with a very polite ghost",
    "a festival cleaning day when something precious is lost", "a robot that takes every instruction literally",
]

STYLES = [
    "pure slapstick chase", "one small lie that snowballs", "a plan that backfires in the worst way",
    "absurd logic treated very seriously", "a rivalry that gets out of hand", "a simple misunderstanding that escalates",
]

CASTS = [
    "two cartoon animals", "two cartoon humans", "one cartoon animal and one cartoon human",
]

def pick():
    return random.choice(SETTINGS), random.choice(STYLES), random.choice(CASTS)
