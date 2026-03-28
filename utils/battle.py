import math
from dataclasses import dataclass
from config.settings import settings


@dataclass
class BattleResult:
    winner_id: int
    loser_id: int
    attacker_soldiers_lost: int
    attacker_dragons_lost: int
    attacker_scorpions_lost: int
    defender_soldiers_lost: int
    defender_dragons_lost: int
    defender_scorpions_lost: int
    loot_gold: int
    loot_soldiers: int
    loot_dragons: int
    battle_log: list


def calculate_battle(
    attacker_house,
    defender_house,
    attacker_gold: int,
    defender_gold: int,
) -> BattleResult:
    """
    Jang formulasi:
    1. Air Phase: 3 Skorpion = 1 Ajdar (Skorpion bir martalik)
    2. Ground Phase: 1 Ajdar = 200 askar. Agar askar 201+ bo'lsa, ajdar o'ladi.
    """
    log = []

    # Nusxalar (o'zgaruvchan)
    att_soldiers = attacker_house.total_soldiers
    att_dragons = attacker_house.total_dragons
    att_scorpions = attacker_house.total_scorpions

    def_soldiers = defender_house.total_soldiers
    def_dragons = defender_house.total_dragons
    def_scorpions = defender_house.total_scorpions

    # --- AIR PHASE ---
    log.append("⚔️ HAVO FAZASI boshlanmoqda...")

    # Mudofaachilarning Skorpionlari hujumchi ajdarlarga qarshi
    if def_scorpions > 0 and att_dragons > 0:
        dragons_killed_by_def = def_scorpions // settings.SCORPIONS_PER_DRAGON
        actual_killed = min(dragons_killed_by_def, att_dragons)
        att_dragons -= actual_killed
        log.append(
            f"🏹 Mudofaa Skorpionlari: {def_scorpions} ta → "
            f"Hujumchi {actual_killed} ta ajdar halok bo'ldi"
        )
    def_scorpions = 0  # Skorpion bir martalik

    # Hujumchilarning Skorpionlari mudofaa ajdarlarga qarshi
    if att_scorpions > 0 and def_dragons > 0:
        dragons_killed_by_att = att_scorpions // settings.SCORPIONS_PER_DRAGON
        actual_killed = min(dragons_killed_by_att, def_dragons)
        def_dragons -= actual_killed
        log.append(
            f"🏹 Hujum Skorpionlari: {att_scorpions} ta → "
            f"Mudofaa {actual_killed} ta ajdar halok bo'ldi"
        )
    att_scorpions = 0

    log.append(
        f"Havo fazasi natijasi: Hujumchi {att_dragons} ajdar | "
        f"Mudofaa {def_dragons} ajdar"
    )

    # --- GROUND PHASE ---
    log.append("⚔️ QURUQLIK FAZASI boshlanmoqda...")

    # Hujumchi ajdarlari mudofaa askarlariga qarshi
    remaining_att_dragons = att_dragons
    while remaining_att_dragons > 0 and def_soldiers > 0:
        # 1 ajdar = 200 askar o'ldiradi, lekin agar 201+ askar bo'lsa ajdar o'ladi
        if def_soldiers > settings.DRAGON_KILLS_SOLDIERS:
            def_soldiers -= settings.DRAGON_KILLS_SOLDIERS
            remaining_att_dragons -= 1
            log.append(f"🐉 Hujumchi ajdar o'ldirildi ({def_soldiers} askar qoldi)")
        else:
            def_soldiers = 0
            remaining_att_dragons -= 1
            log.append(f"🐉 Hujumchi ajdar {settings.DRAGON_KILLS_SOLDIERS} askar o'ldirdi")
    att_dragons_lost_ground = att_dragons - remaining_att_dragons
    att_dragons = remaining_att_dragons

    # Mudofaa ajdarlari hujumchi askarlariga qarshi
    remaining_def_dragons = def_dragons
    while remaining_def_dragons > 0 and att_soldiers > 0:
        if att_soldiers > settings.DRAGON_KILLS_SOLDIERS:
            att_soldiers -= settings.DRAGON_KILLS_SOLDIERS
            remaining_def_dragons -= 1
            log.append(f"🐉 Mudofaa ajdar o'ldirildi ({att_soldiers} askar qoldi)")
        else:
            att_soldiers = 0
            remaining_def_dragons -= 1
            log.append(f"🐉 Mudofaa ajdar {settings.DRAGON_KILLS_SOLDIERS} askar o'ldirdi")
    def_dragons_lost_ground = def_dragons - remaining_def_dragons
    def_dragons = remaining_def_dragons

    # Askarlar o'rtasidagi jang (oddiy nisbat)
    if att_soldiers > 0 and def_soldiers > 0:
        total = att_soldiers + def_soldiers
        att_ratio = att_soldiers / total
        def_ratio = def_soldiers / total
        att_lost = math.ceil(def_soldiers * def_ratio)
        def_lost = math.ceil(att_soldiers * att_ratio)
        att_soldiers = max(0, att_soldiers - att_lost)
        def_soldiers = max(0, def_soldiers - def_lost)
        log.append(
            f"⚔️ Askar jangi: Hujumchi -{att_lost} | Mudofaa -{def_lost}"
        )

    # G'olib aniqlash
    att_power = att_soldiers + att_dragons * settings.DRAGON_KILLS_SOLDIERS
    def_power = def_soldiers + def_dragons * settings.DRAGON_KILLS_SOLDIERS

    log.append(f"\n📊 Yakuniy kuch: Hujumchi {att_power} | Mudofaa {def_power}")

    attacker_wins = att_power >= def_power

    # O'lja hisoblash
    total_defender_gold = defender_gold
    loot_gold = math.ceil(total_defender_gold * settings.WAR_LOOT_PERCENT)
    loot_soldiers = math.ceil(defender_house.total_soldiers * settings.WAR_LOOT_PERCENT) if attacker_wins else 0
    loot_dragons = math.ceil(defender_house.total_dragons * settings.WAR_LOOT_PERCENT) if attacker_wins else 0

    winner_id = attacker_house.id if attacker_wins else defender_house.id
    loser_id = defender_house.id if attacker_wins else attacker_house.id

    # Yo'qotmalar hisoblash
    att_soldiers_lost = attacker_house.total_soldiers - att_soldiers
    att_dragons_lost = attacker_house.total_dragons - att_dragons
    att_scorpions_lost = attacker_house.total_scorpions  # Hammasi ishlatildi

    def_soldiers_lost = defender_house.total_soldiers - def_soldiers
    def_dragons_lost = defender_house.total_dragons - def_dragons
    def_scorpions_lost = defender_house.total_scorpions

    if attacker_wins:
        log.append(f"\n🏆 G'OLIB: {attacker_house.name}")
        log.append(f"💰 O'lja: {loot_gold} oltin")
    else:
        log.append(f"\n🏆 G'OLIB: {defender_house.name}")
        log.append(f"💰 O'lja: {loot_gold} oltin")

    return BattleResult(
        winner_id=winner_id,
        loser_id=loser_id,
        attacker_soldiers_lost=att_soldiers_lost,
        attacker_dragons_lost=att_dragons_lost,
        attacker_scorpions_lost=att_scorpions_lost,
        defender_soldiers_lost=def_soldiers_lost,
        defender_dragons_lost=def_dragons_lost,
        defender_scorpions_lost=def_scorpions_lost,
        loot_gold=loot_gold,
        loot_soldiers=loot_soldiers,
        loot_dragons=loot_dragons,
        battle_log=log,
    )


def calculate_surrender_loot(defender_gold: int, defender_soldiers: int, defender_dragons: int) -> dict:
    """Taslim bo'lish: 50% resursni berish"""
    return {
        "gold": math.ceil(defender_gold * settings.SURRENDER_LOOT_PERCENT),
        "soldiers": math.ceil(defender_soldiers * settings.SURRENDER_LOOT_PERCENT),
        "dragons": math.ceil(defender_dragons * settings.SURRENDER_LOOT_PERCENT),
    }
