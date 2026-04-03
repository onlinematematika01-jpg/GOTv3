import math
from dataclasses import dataclass, field
from config.settings import settings


@dataclass
class RoundResult:
    round_num: int
    attacker_wins: bool
    log: list = field(default_factory=list)


@dataclass
class AllyContribution:
    house_id: int
    house_name: str
    join_type: str        # "full" = jangga qo'shilish | "soldiers" = yordam yuborish
    soldiers: int = 0
    dragons: int = 0
    scorpions: int = 0
    custom_items: list = None  # [{"item": CustomItem, "qty": int}]


@dataclass
class BattleResult:
    winner_id: int
    loser_id: int
    attacker_wins: bool
    attacker_soldiers_lost: int
    attacker_dragons_lost: int
    attacker_scorpions_lost: int
    defender_soldiers_lost: int
    defender_dragons_lost: int
    defender_scorpions_lost: int
    attacker_ally_losses: dict   # {house_id: {soldiers, dragons, scorpions}}
    defender_ally_losses: dict
    loot_gold: int
    loot_soldiers: int
    loot_dragons: int
    round_results: list
    battle_log: list



def _apply_custom_items(house, allies: list, soldiers: int, dragons: int, scorpions: int):
    """
    Xonadon va ittifoqchilarning custom itemlari kuchini
    askar/ajdar/chayon ekvivalentiga o'giradi va qo'shadi.

    Item turlari:
      ATTACK  → attack_power * qty  → dragons ekvivalenti (ajdar kabi ishlaydi)
      DEFENSE → defense_power * qty → scorpions ekvivalenti (chayon kabi ishlaydi)
      SOLDIER → attack_power * qty  → soldiers ekvivalenti
    """
    from database.models import ItemTypeEnum

    # Xonadon custom itemlari
    house_items = getattr(house, '_custom_items', []) or []
    for entry in house_items:
        item = entry["item"]
        qty  = entry["qty"]
        if item.item_type == ItemTypeEnum.ATTACK:
            dragons   += item.attack_power * qty
        elif item.item_type == ItemTypeEnum.DEFENSE:
            scorpions += item.defense_power * qty
        elif item.item_type == ItemTypeEnum.SOLDIER:
            soldiers  += item.attack_power * qty

    # Ittifoqchi custom itemlari
    for ally in allies:
        ally_items = getattr(ally, 'custom_items', None) or []
        for entry in ally_items:
            item = entry["item"]
            qty  = entry["qty"]
            if item.item_type == ItemTypeEnum.ATTACK:
                dragons   += item.attack_power * qty
            elif item.item_type == ItemTypeEnum.DEFENSE:
                scorpions += item.defense_power * qty
            elif item.item_type == ItemTypeEnum.SOLDIER:
                soldiers  += item.attack_power * qty

    return soldiers, dragons, scorpions


def calculate_battle(
    attacker_house,
    defender_house,
    defender_gold: int,
    attacker_allies: list = None,
    defender_allies: list = None,
) -> BattleResult:
    """
    3 Roundlik urush mexanikasi:
      Round 1 — Ajdar vs Skorpion
      Round 2 — Ajdar vs Askar
      Round 3 — Askar vs Askar
      G'OLIB: 3-ROUND natijasi hal qiladi
    """
    if attacker_allies is None:
        attacker_allies = []
    if defender_allies is None:
        defender_allies = []

    log = []
    round_results = []

    att_soldiers  = attacker_house.total_soldiers  + sum(a.soldiers  for a in attacker_allies)
    att_dragons   = attacker_house.total_dragons   + sum(a.dragons   for a in attacker_allies)
    att_scorpions = attacker_house.total_scorpions + sum(a.scorpions for a in attacker_allies)

    def_soldiers  = defender_house.total_soldiers  + sum(a.soldiers  for a in defender_allies)
    def_dragons   = defender_house.total_dragons   + sum(a.dragons   for a in defender_allies)
    def_scorpions = defender_house.total_scorpions + sum(a.scorpions for a in defender_allies)

    # ── Custom itemlar kuchini hisoblash ──────────────────────────────────
    att_soldiers, att_dragons, att_scorpions = _apply_custom_items(
        attacker_house, attacker_allies, att_soldiers, att_dragons, att_scorpions
    )
    def_soldiers, def_dragons, def_scorpions = _apply_custom_items(
        defender_house, defender_allies, def_soldiers, def_dragons, def_scorpions
    )

    # Custom itemlar haqida qisqacha ma'lumot
    def _custom_items_summary(house) -> str:
        items = getattr(house, '_custom_items', []) or []
        if not items:
            return ""
        parts = [f"{e['item'].emoji}{e['item'].name}×{e['qty']}" for e in items]
        return " | " + " ".join(parts)

    log.append(
        f"⚔️ <b>JANG BOSHLANMOQDA!</b>\n"
        f"🔴 {attacker_house.name}: {att_soldiers} askar | {att_dragons} ajdar | {att_scorpions} skorpion"
        f"{_custom_items_summary(attacker_house)}\n"
        f"🔵 {defender_house.name}: {def_soldiers} askar | {def_dragons} ajdar | {def_scorpions} skorpion"
        f"{_custom_items_summary(defender_house)}"
    )
    if attacker_allies:
        log.append("🤝 Hujumchi ittifoqchilari: " + ", ".join(a.house_name for a in attacker_allies))
    if defender_allies:
        log.append("🤝 Mudofaachi ittifoqchilari: " + ", ".join(a.house_name for a in defender_allies))

    # ═══════════════════════════════════════
    # QAL'A MUDOFAASI — Roundlardan oldin
    # ═══════════════════════════════════════
    castle_defense = getattr(defender_house, 'castle_defense', 0) or 0
    castle_triggered = False

    if castle_defense > 0:
        log.append(f"\n🏰 <b>QAL'A MUDOFAASI FAOLLASHDI!</b>\nMudofaa balli: {castle_defense} | Hujumchi ajdarlari: {att_dragons}")
        if castle_defense > att_dragons:
            # Qal'a hujumchining barcha resurslarini yarmilashtiradi
            att_soldiers  = math.ceil(att_soldiers  / 2)
            att_dragons   = math.ceil(att_dragons   / 2)
            att_scorpions = math.ceil(att_scorpions / 2)
            castle_triggered = True
            log.append(
                f"🏰 Qal'a mudofaa balli ({castle_defense}) hujumchi ajdarlaridan ({att_dragons*2}) ko'p!\n"
                f"💥 Hujumchining barcha resurslari yarimlandi:\n"
                f"🔴 {attacker_house.name}: {att_soldiers} askar | {att_dragons} ajdar | {att_scorpions} skorpion"
            )
            # Qal'a bir marta ishlatiladi — ballni nolga tushirish
            defender_house.castle_defense = 0
        else:
            log.append(f"🏰 Qal'a mudofaasi yetarli emas (mudofaa {castle_defense} ≤ ajdar {att_dragons}) — ta'sir yo'q")

    # ═══════════════════════════════════════
    # ROUND 1 — Ajdar vs Skorpion
    # ═══════════════════════════════════════
    r1_log = ["", "🔥 <b>1-ROUND: AJDAR vs SKORPION</b>"]

    # Ikkala tomon bir vaqtda o'q uzadi
    def_dragons_killed = 0
    att_dragons_killed = 0

    if def_scorpions > 0 and att_dragons > 0:
        def_dragons_killed = min(def_scorpions // settings.SCORPIONS_PER_DRAGON, att_dragons)
        r1_log.append(
            f"🏹 {defender_house.name} skorpionlari ({def_scorpions} ta) → "
            f"hujumchi {def_dragons_killed} ajdar halok"
        )

    if att_scorpions > 0 and def_dragons > 0:
        att_dragons_killed = min(att_scorpions // settings.SCORPIONS_PER_DRAGON, def_dragons)
        r1_log.append(
            f"🏹 {attacker_house.name} skorpionlari ({att_scorpions} ta) → "
            f"mudofaachi {att_dragons_killed} ajdar halok"
        )

    att_dragons   -= def_dragons_killed
    def_dragons   -= att_dragons_killed
    att_scorpions  = 0
    def_scorpions  = 0

    r1_log.append(
        f"📊 Natija: Hujumchi {att_dragons} ajdar | Mudofaachi {def_dragons} ajdar qoldi"
    )

    # Ko'proq ajdar yo'q qilgan tomon yutadi
    r1_att_wins = def_dragons_killed >= att_dragons_killed
    r1_log.append(
        f"{'🔴 Hujumchi' if r1_att_wins else '🔵 Mudofaachi'} 1-Roundni yutdi"
    )
    round_results.append(RoundResult(1, r1_att_wins, r1_log))
    log.extend(r1_log)

    # ═══════════════════════════════════════
    # ROUND 2 — Ajdar vs Askar
    # ═══════════════════════════════════════
    r2_log = ["", "🐉 <b>2-ROUND: AJDAR vs ASKAR</b>"]

    # Hujumchi ajdarlari mudofaachi askarlariga qarshi
    remaining_att_dragons = att_dragons
    while remaining_att_dragons > 0 and def_soldiers > 0:
        if def_soldiers > settings.DRAGON_KILLS_SOLDIERS:
            # 201+ askar: ajdar o'ladi, 200 askar o'ladi, qolganlar keyingi ajdarga qarshi
            def_soldiers -= settings.DRAGON_KILLS_SOLDIERS
            remaining_att_dragons -= 1
            r2_log.append(
                f"🐉 Hujumchi ajdari {settings.DRAGON_KILLS_SOLDIERS} askar o'ldirdi, halok bo'ldi "
                f"({def_soldiers} mudofaachi askari qoldi)"
            )
        else:
            # <=200 askar: ajdar TIRIK qoladi, askarning yarmi o'ladi, loop to'xtaydi
            half = math.ceil(def_soldiers / 2)
            def_soldiers -= half
            r2_log.append(
                f"🐉 Hujumchi ajdari {half} askar o'ldirdi, ajdar TIRIK qoldi "
                f"({def_soldiers} mudofaachi askari qoldi)"
            )
            break
    att_dragons = remaining_att_dragons

    # Mudofaachi ajdarlari hujumchi askarlariga qarshi
    remaining_def_dragons = def_dragons
    while remaining_def_dragons > 0 and att_soldiers > 0:
        if att_soldiers > settings.DRAGON_KILLS_SOLDIERS:
            # 201+ askar: ajdar o'ladi, 200 askar o'ladi, qolganlar keyingi ajdarga qarshi
            att_soldiers -= settings.DRAGON_KILLS_SOLDIERS
            remaining_def_dragons -= 1
            r2_log.append(
                f"🐉 Mudofaachi ajdari {settings.DRAGON_KILLS_SOLDIERS} askar o'ldirdi, halok bo'ldi "
                f"({att_soldiers} hujumchi askari qoldi)"
            )
        else:
            # <=200 askar: ajdar TIRIK qoladi, askarning yarmi o'ladi, loop to'xtaydi
            half = math.ceil(att_soldiers / 2)
            att_soldiers -= half
            r2_log.append(
                f"🐉 Mudofaachi ajdari {half} askar o'ldirdi, ajdar TIRIK qoldi "
                f"({att_soldiers} hujumchi askari qoldi)"
            )
            break
    def_dragons = remaining_def_dragons

    att_power_r2 = att_soldiers + att_dragons * settings.DRAGON_KILLS_SOLDIERS
    def_power_r2 = def_soldiers + def_dragons * settings.DRAGON_KILLS_SOLDIERS
    r2_log.append(
        f"📊 Natija: Hujumchi kuch {att_power_r2} | Mudofaachi kuch {def_power_r2}"
    )

    r2_att_wins = att_power_r2 >= def_power_r2
    r2_log.append(
        f"{'🔴 Hujumchi' if r2_att_wins else '🔵 Mudofaachi'} 2-Roundni yutdi"
    )
    round_results.append(RoundResult(2, r2_att_wins, r2_log))
    log.extend(r2_log)

    # ═══════════════════════════════════════
    # ROUND 3 — Askar vs Askar
    # ═══════════════════════════════════════
    r3_log = ["", "⚔️ <b>3-ROUND: ASKAR vs ASKAR</b>"]

    if att_soldiers == 0 and def_soldiers == 0:
        r3_att_wins = att_dragons >= def_dragons
        r3_log.append("⚠️ Ikkala tomon askarsiz — qolgan ajdar soni hal qiladi")
    elif att_soldiers == 0:
        r3_att_wins = False
        r3_log.append("⚠️ Hujumchida askar qolmadi")
    elif def_soldiers == 0:
        r3_att_wins = True
        r3_log.append("⚠️ Mudofaachida askar qolmadi")
    else:
        total = att_soldiers + def_soldiers
        att_ratio = att_soldiers / total
        def_ratio = def_soldiers / total

        # Kuchliroq tomon kamroq yo'qotadi, max 30% cheklov
        att_lost = min(math.ceil(att_soldiers * def_ratio * 0.6), math.ceil(att_soldiers * 0.30))
        def_lost = min(math.ceil(def_soldiers * att_ratio * 0.6), math.ceil(def_soldiers * 0.30))

        att_soldiers = max(0, att_soldiers - att_lost)
        def_soldiers = max(0, def_soldiers - def_lost)

        r3_log.append(f"⚔️ Hujumchi -{att_lost} askar | Mudofaachi -{def_lost} askar")
        r3_log.append(
            f"📊 Natija: Hujumchi {att_soldiers} askar | Mudofaachi {def_soldiers} askar qoldi"
        )
        r3_att_wins = att_soldiers >= def_soldiers

    r3_log.append(
        f"{'🔴 Hujumchi' if r3_att_wins else '🔵 Mudofaachi'} 3-Roundni yutdi"
    )
    round_results.append(RoundResult(3, r3_att_wins, r3_log))
    log.extend(r3_log)

    # ═══════════════════════════════════════
    # YAKUNIY G'OLIB — 3-ROUND hal qiladi
    # ═══════════════════════════════════════
    attacker_wins = r3_att_wins
    winner_id   = attacker_house.id   if attacker_wins else defender_house.id
    loser_id    = defender_house.id   if attacker_wins else attacker_house.id
    winner_name = attacker_house.name if attacker_wins else defender_house.name

    log.append(
        f"\n🏁 <b>JANG NATIJASI</b>\n"
        f"1-Round: {'🔴 Hujumchi' if r1_att_wins else '🔵 Mudofaachi'}\n"
        f"2-Round: {'🔴 Hujumchi' if r2_att_wins else '🔵 Mudofaachi'}\n"
        f"3-Round: {'🔴 Hujumchi' if r3_att_wins else '🔵 Mudofaachi'}\n"
        f"🏆 <b>G'OLIB: {winner_name}</b>"
    )

    # ═══════════════════════════════════════
    # YO'QOTMALAR
    # ═══════════════════════════════════════
    att_total_start = attacker_house.total_soldiers + sum(a.soldiers for a in attacker_allies)
    def_total_start = defender_house.total_soldiers + sum(a.soldiers for a in defender_allies)

    att_dragons_start = attacker_house.total_dragons + sum(a.dragons for a in attacker_allies)
    def_dragons_start = defender_house.total_dragons + sum(a.dragons for a in defender_allies)

    att_soldiers_lost  = max(0, att_total_start - att_soldiers)
    att_dragons_lost   = max(0, att_dragons_start - att_dragons)
    att_scorpions_lost = attacker_house.total_scorpions

    def_soldiers_lost  = max(0, def_total_start - def_soldiers)
    def_dragons_lost   = max(0, def_dragons_start - def_dragons)
    def_scorpions_lost = defender_house.total_scorpions

    # Ittifoqchi yo'qotmalari
    def _ally_loss(ally, side_wins, side_soldiers_lost, side_total_soldiers):
        if side_wins:
            if ally.join_type == "soldiers":
                # Askarlar to'liq qaytadi
                return {"soldiers": 0, "dragons": 0, "scorpions": 0}
            else:
                # "full" — proportional yo'qotish
                ratio = (ally.soldiers / side_total_soldiers) if side_total_soldiers > 0 else 0
                return {
                    "soldiers": math.floor(side_soldiers_lost * ratio),
                    "dragons": ally.dragons,
                    "scorpions": ally.scorpions,
                }
        else:
            # Mag'lubiyat — hammasi yo'qoladi
            return {
                "soldiers": ally.soldiers,
                "dragons": ally.dragons if ally.join_type == "full" else 0,
                "scorpions": ally.scorpions if ally.join_type == "full" else 0,
            }

    attacker_ally_losses = {
        a.house_id: _ally_loss(a, attacker_wins, att_soldiers_lost, att_total_start)
        for a in attacker_allies
    }
    defender_ally_losses = {
        a.house_id: _ally_loss(a, not attacker_wins, def_soldiers_lost, def_total_start)
        for a in defender_allies
    }

    # ═══════════════════════════════════════
    # O'LJA
    # ═══════════════════════════════════════
    loot_gold     = math.ceil(defender_gold                     * settings.WAR_LOOT_PERCENT) if attacker_wins else 0
    loot_soldiers = math.ceil(defender_house.total_soldiers     * settings.WAR_LOOT_PERCENT) if attacker_wins else 0
    loot_dragons  = math.ceil(defender_house.total_dragons      * settings.WAR_LOOT_PERCENT) if attacker_wins else 0

    if attacker_wins:
        log.append(f"💰 O'lja: {loot_gold} oltin | 🗡️ {loot_soldiers} askar | 🐉 {loot_dragons} ajdar")

    return BattleResult(
        winner_id=winner_id,
        loser_id=loser_id,
        attacker_wins=attacker_wins,
        attacker_soldiers_lost=att_soldiers_lost,
        attacker_dragons_lost=att_dragons_lost,
        attacker_scorpions_lost=att_scorpions_lost,
        defender_soldiers_lost=def_soldiers_lost,
        defender_dragons_lost=def_dragons_lost,
        defender_scorpions_lost=def_scorpions_lost,
        attacker_ally_losses=attacker_ally_losses,
        defender_ally_losses=defender_ally_losses,
        loot_gold=loot_gold,
        loot_soldiers=loot_soldiers,
        loot_dragons=loot_dragons,
        round_results=round_results,
        battle_log=log,
    )


def calculate_surrender_loot(defender_gold: int, defender_soldiers: int, defender_dragons: int) -> dict:
    """Taslim bo'lish: 50% resursni berish"""
    return {
        "gold":     math.ceil(defender_gold     * settings.SURRENDER_LOOT_PERCENT),
        "soldiers": math.ceil(defender_soldiers * settings.SURRENDER_LOOT_PERCENT),
        "dragons":  math.ceil(defender_dragons  * settings.SURRENDER_LOOT_PERCENT),
    }
