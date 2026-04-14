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


def _collect_custom_items(house, allies: list):
    """
    Xonadon va ittifoqchilarning custom itemlarini yig'ib,
    tur bo'yicha ajratib qaytaradi.

    Qaytaradi: {
        "attack":  [ {"name": ..., "emoji": ..., "attack_power": N,  "qty": Q}, ... ],
        "defense": [ {"name": ..., "emoji": ..., "defense_power": M, "qty": Q}, ... ],
        "soldier": [ {"name": ..., "emoji": ..., "attack_power": N,  "qty": Q}, ... ],
    }
    """
    from database.models import ItemTypeEnum

    result = {"attack": [], "defense": [], "soldier": []}

    def _add(item, qty):
        if qty <= 0:
            return
        if item.item_type == ItemTypeEnum.ATTACK:
            result["attack"].append({
                "item_id": item.id, "name": item.name, "emoji": item.emoji,
                "attack_power": item.attack_power, "qty": qty,
            })
        elif item.item_type == ItemTypeEnum.DEFENSE:
            result["defense"].append({
                "item_id": item.id, "name": item.name, "emoji": item.emoji,
                "defense_power": item.defense_power, "qty": qty,
            })
        elif item.item_type == ItemTypeEnum.SOLDIER:
            result["soldier"].append({
                "item_id": item.id, "name": item.name, "emoji": item.emoji,
                "attack_power": item.attack_power, "qty": qty,
            })

    for entry in (getattr(house, '_custom_items', []) or []):
        _add(entry["item"], entry["qty"])

    for ally in allies:
        for entry in (getattr(ally, 'custom_items', None) or []):
            _add(entry["item"], entry["qty"])

    return result


def _items_summary(items_dict: dict) -> str:
    parts = []
    for group in items_dict.values():
        for it in group:
            parts.append(f"{it['emoji']}{it['name']}×{it['qty']}")
    return (" | " + " ".join(parts)) if parts else ""


def calculate_battle(
    attacker_house,
    defender_house,
    defender_gold: int,
    attacker_allies: list = None,
    defender_allies: list = None,
) -> BattleResult:
    """
    3 Roundlik urush mexanikasi:

      Round 1 — Ajdar vs Skorpion  (+DEFENSE itemlar skorpion kabi ishlaydi)
      Round 2 — Ajdar vs Askar     (+ATTACK itemlar ajdar kabi ishlaydi, SOLDIER itemlar askar kabi)
      Round 3 — Askar vs Askar     (+SOLDIER itemlar askar kabi ishlaydi)

    Custom item mexanikasi:
      ATTACK  item (attack_power=N): 1 ta item = N askarni yo'q qila oladi (ajdar kabi).
              Uni o'ldirish uchun N+1 askar kerak. Uni o'ldirish uchun ajdar:
              1 ajdar = DRAGON_KILLS_SOLDIERS askar ekvivalenti, item = N askar →
              math.ceil(DRAGON_KILLS_SOLDIERS / N) ta item = 1 ajdar.
              DEFENSE itemlar bu itemga ta'sir o'tkaza olmaydi (defense_power=0 bo'lsa).

      DEFENSE item (defense_power=M): 1 ta item = M ta skorpion ekvivalenti (Round 1 da).
              Agar M=0 bo'lsa, skorpionlar bu itemga ta'sir qila olmaydi.

      SOLDIER item (attack_power=N): 1 ta item = N ta qo'shimcha askar (Round 2 va 3 da).

    G'OLIB: 3-ROUND natijasi hal qiladi.
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

    # Custom itemlarni yig'ish (alohida birlik sifatida)
    att_items = _collect_custom_items(attacker_house, attacker_allies)
    def_items = _collect_custom_items(defender_house, defender_allies)

    # SOLDIER itemlarni darhol askarlarga qo'shish (ular hamma roundda askar kabi ishlaydi)
    att_soldier_item_bonus = sum(it["attack_power"] * it["qty"] for it in att_items["soldier"])
    def_soldier_item_bonus = sum(it["attack_power"] * it["qty"] for it in def_items["soldier"])

    for it in att_items["soldier"]:
        att_soldiers += it["attack_power"] * it["qty"]
    for it in def_items["soldier"]:
        def_soldiers += it["attack_power"] * it["qty"]

    log.append(
        f"⚔️ <b>JANG BOSHLANMOQDA!</b>\n"
        f"🔴 {attacker_house.name}: {att_soldiers} askar | {att_dragons} ajdar | {att_scorpions} skorpion"
        f"{_items_summary({'a': att_items['attack'], 'd': att_items['defense']})}\n"
        f"🔵 {defender_house.name}: {def_soldiers} askar | {def_dragons} ajdar | {def_scorpions} skorpion"
        f"{_items_summary({'a': def_items['attack'], 'd': def_items['defense']})}"
    )
    if attacker_allies:
        log.append("🤝 Hujumchi ittifoqchilari: " + ", ".join(a.house_name for a in attacker_allies))
    if defender_allies:
        log.append("🤝 Mudofaachi ittifoqchilari: " + ", ".join(a.house_name for a in defender_allies))

    # ═══════════════════════════════════════
    # QAL'A MUDOFAASI — Roundlardan oldin
    # ═══════════════════════════════════════
    castle_defense = getattr(defender_house, 'castle_defense', 0) or 0

    if castle_defense > 0:
        log.append(f"\n🏰 <b>QAL'A MUDOFAASI FAOLLASHDI!</b>\nMudofaa balli: {castle_defense} | Hujumchi ajdarlari: {att_dragons}")
        if castle_defense > att_dragons:
            att_soldiers  = math.ceil(att_soldiers  / 2)
            att_dragons   = math.ceil(att_dragons   / 2)
            att_scorpions = math.ceil(att_scorpions / 2)
            # ATTACK itemlar ham yarmilanadi
            for it in att_items["attack"]:
                it["qty"] = math.ceil(it["qty"] / 2)
            log.append(
                f"🏰 Qal'a mudofaa balli ({castle_defense}) hujumchi ajdarlaridan ko'p!\n"
                f"💥 Hujumchining barcha resurslari yarimlandi:\n"
                f"🔴 {attacker_house.name}: {att_soldiers} askar | {att_dragons} ajdar | {att_scorpions} skorpion"
            )
            defender_house.castle_defense = 0
        else:
            log.append(f"🏰 Qal'a mudofaasi yetarli emas (mudofaa {castle_defense} ≤ ajdar {att_dragons}) — ta'sir yo'q")

    # ═══════════════════════════════════════
    # ROUND 1 — Ajdar vs Skorpion
    #           + DEFENSE itemlar skorpion kabi ishlaydi
    # ═══════════════════════════════════════
    r1_log = ["", "🔥 <b>1-ROUND: AJDAR vs SKORPION</b>"]

    def_dragons_killed = 0
    att_dragons_killed = 0

    # --- Mudofaachining skorpionlari hujumchi ajdarlariga qarshi ---
    if def_scorpions > 0 and att_dragons > 0:
        killed = min(def_scorpions // settings.SCORPIONS_PER_DRAGON, att_dragons)
        def_dragons_killed += killed
        att_dragons -= killed
        r1_log.append(
            f"🏹 {defender_house.name} skorpionlari ({def_scorpions} ta) → "
            f"hujumchi {killed} ajdar halok"
        )

    # --- Mudofaachining DEFENSE itemlari hujumchi ajdarlariga qarshi ---
    for it in def_items["defense"]:
        if it["defense_power"] <= 0 or att_dragons <= 0:
            continue
        total_scorp_equiv = it["defense_power"] * it["qty"]
        killed = min(total_scorp_equiv // settings.SCORPIONS_PER_DRAGON, att_dragons)
        if killed > 0:
            def_dragons_killed += killed
            att_dragons -= killed
            r1_log.append(
                f"🛡 {defender_house.name} {it['emoji']}{it['name']}×{it['qty']} "
                f"({total_scorp_equiv} skorpion ekvivalenti) → hujumchi {killed} ajdar halok"
            )

    # --- Hujumchining skorpionlari mudofaachi ajdarlariga qarshi ---
    if att_scorpions > 0 and def_dragons > 0:
        killed = min(att_scorpions // settings.SCORPIONS_PER_DRAGON, def_dragons)
        att_dragons_killed += killed
        def_dragons -= killed
        r1_log.append(
            f"🏹 {attacker_house.name} skorpionlari ({att_scorpions} ta) → "
            f"mudofaachi {killed} ajdar halok"
        )

    # --- Hujumchining DEFENSE itemlari mudofaachi ajdarlariga qarshi ---
    for it in att_items["defense"]:
        if it["defense_power"] <= 0 or def_dragons <= 0:
            continue
        total_scorp_equiv = it["defense_power"] * it["qty"]
        killed = min(total_scorp_equiv // settings.SCORPIONS_PER_DRAGON, def_dragons)
        if killed > 0:
            att_dragons_killed += killed
            def_dragons -= killed
            r1_log.append(
                f"🛡 {attacker_house.name} {it['emoji']}{it['name']}×{it['qty']} "
                f"({total_scorp_equiv} skorpion ekvivalenti) → mudofaachi {killed} ajdar halok"
            )

    # Faqat ishlatilgan skorpionlarni ayiramiz (ajdarga duch kelgan)
    att_scorpions_used = min(att_scorpions, att_dragons_killed * settings.SCORPIONS_PER_DRAGON)
    def_scorpions_used = min(def_scorpions, def_dragons_killed * settings.SCORPIONS_PER_DRAGON)
    att_scorpions -= att_scorpions_used
    def_scorpions -= def_scorpions_used

    r1_log.append(
        f"📊 Natija: Hujumchi {att_dragons} ajdar | Mudofaachi {def_dragons} ajdar qoldi"
    )
    r1_att_wins = def_dragons_killed >= att_dragons_killed
    r1_log.append(
        f"{'🔴 Hujumchi' if r1_att_wins else '🔵 Mudofaachi'} 1-Roundni yutdi"
    )
    round_results.append(RoundResult(1, r1_att_wins, r1_log))
    log.extend(r1_log)

    # ═══════════════════════════════════════
    # ROUND 2 — Ajdar vs Askar
    #           + ATTACK itemlar ajdar kabi ishlaydi
    # ═══════════════════════════════════════
    r2_log = ["", "🐉 <b>2-ROUND: AJDAR vs ASKAR</b>"]

    # --- Hujumchi ajdarlari mudofaachi askarlariga qarshi ---
    remaining_att_dragons = att_dragons
    while remaining_att_dragons > 0 and def_soldiers > 0:
        if def_soldiers > settings.DRAGON_KILLS_SOLDIERS:
            def_soldiers -= settings.DRAGON_KILLS_SOLDIERS
            remaining_att_dragons -= 1
            r2_log.append(
                f"🐉 Hujumchi ajdari {settings.DRAGON_KILLS_SOLDIERS} askar o'ldirdi, halok bo'ldi "
                f"({def_soldiers} mudofaachi askari qoldi)"
            )
        else:
            half = math.ceil(def_soldiers / 2)
            def_soldiers -= half
            r2_log.append(
                f"🐉 Hujumchi ajdari {half} askar o'ldirdi, ajdar TIRIK qoldi "
                f"({def_soldiers} mudofaachi askari qoldi)"
            )
            break
    att_dragons = remaining_att_dragons

    # --- Hujumchi ATTACK itemlari mudofaachi askarlariga qarshi ---
    # 1 item = attack_power askar yo'q qiladi, o'lishi uchun attack_power+1 askar kerak
    for it in att_items["attack"]:
        if it["attack_power"] <= 0 or def_soldiers <= 0:
            continue
        remaining_items = it["qty"]
        while remaining_items > 0 and def_soldiers > 0:
            kills = it["attack_power"]
            if def_soldiers > kills:
                def_soldiers -= kills
                remaining_items -= 1
                r2_log.append(
                    f"⚔️ Hujumchi {it['emoji']}{it['name']} {kills} askar o'ldirdi, halok bo'ldi "
                    f"({def_soldiers} mudofaachi askari qoldi)"
                )
            else:
                # Askar soni itemni o'ldirish uchun yetarli emas — item tirik qoladi
                half = math.ceil(def_soldiers / 2)
                def_soldiers -= half
                r2_log.append(
                    f"⚔️ Hujumchi {it['emoji']}{it['name']} {half} askar o'ldirdi, item TIRIK qoldi "
                    f"({def_soldiers} mudofaachi askari qoldi)"
                )
                break
        it["qty"] = remaining_items  # Qolgan itemlar soni yangilanadi

    # --- Mudofaachi ajdarlari hujumchi askarlariga qarshi ---
    remaining_def_dragons = def_dragons
    while remaining_def_dragons > 0 and att_soldiers > 0:
        if att_soldiers > settings.DRAGON_KILLS_SOLDIERS:
            att_soldiers -= settings.DRAGON_KILLS_SOLDIERS
            remaining_def_dragons -= 1
            r2_log.append(
                f"🐉 Mudofaachi ajdari {settings.DRAGON_KILLS_SOLDIERS} askar o'ldirdi, halok bo'ldi "
                f"({att_soldiers} hujumchi askari qoldi)"
            )
        else:
            half = math.ceil(att_soldiers / 2)
            att_soldiers -= half
            r2_log.append(
                f"🐉 Mudofaachi ajdari {half} askar o'ldirdi, ajdar TIRIK qoldi "
                f"({att_soldiers} hujumchi askari qoldi)"
            )
            break
    def_dragons = remaining_def_dragons

    # --- Mudofaachi ATTACK itemlari hujumchi askarlariga qarshi ---
    for it in def_items["attack"]:
        if it["attack_power"] <= 0 or att_soldiers <= 0:
            continue
        remaining_items = it["qty"]
        while remaining_items > 0 and att_soldiers > 0:
            kills = it["attack_power"]
            if att_soldiers > kills:
                att_soldiers -= kills
                remaining_items -= 1
                r2_log.append(
                    f"⚔️ Mudofaachi {it['emoji']}{it['name']} {kills} askar o'ldirdi, halok bo'ldi "
                    f"({att_soldiers} hujumchi askari qoldi)"
                )
            else:
                half = math.ceil(att_soldiers / 2)
                att_soldiers -= half
                r2_log.append(
                    f"⚔️ Mudofaachi {it['emoji']}{it['name']} {half} askar o'ldirdi, item TIRIK qoldi "
                    f"({att_soldiers} hujumchi askari qoldi)"
                )
                break
        it["qty"] = remaining_items

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
    # (SOLDIER itemlar allaqachon att_soldiers/def_soldiers ga qo'shilgan)
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
    att_real_soldiers_start = attacker_house.total_soldiers + sum(a.soldiers for a in attacker_allies)
    def_real_soldiers_start = defender_house.total_soldiers + sum(a.soldiers for a in defender_allies)
    att_total_start   = att_real_soldiers_start + att_soldier_item_bonus
    def_total_start   = def_real_soldiers_start + def_soldier_item_bonus
    att_dragons_start = attacker_house.total_dragons  + sum(a.dragons  for a in attacker_allies)
    def_dragons_start = defender_house.total_dragons  + sum(a.dragons  for a in defender_allies)

    # Jami yo'qotilgan (askar + item ekvivalenti)
    att_total_lost = max(0, att_total_start - att_soldiers)
    def_total_lost = max(0, def_total_start - def_soldiers)

    # Haqiqiy askar yo'qotishlari: item bonusidan ortiq bo'lsa faqat haqiqiy askarlar kamayadi
    # Item bonusi birinchi "sarf" bo'ladi, keyin haqiqiy askarlar
    att_soldiers_lost  = max(0, min(att_real_soldiers_start, att_total_lost - att_soldier_item_bonus))
    def_soldiers_lost  = max(0, min(def_real_soldiers_start, def_total_lost - def_soldier_item_bonus))

    att_dragons_lost   = max(0, att_dragons_start - att_dragons)
    att_scorpions_lost = att_scorpions_used  # faqat ajdarni o'ldirgan skorpionlar yo'qoladi

    def_dragons_lost   = max(0, def_dragons_start - def_dragons)
    def_scorpions_lost = def_scorpions_used  # faqat ajdarni o'ldirgan skorpionlar yo'qoladi

    # Ittifoqchi yo'qotmalari
    def _ally_loss(ally, side_wins, side_soldiers_lost, side_total_soldiers):
        if side_wins:
            if ally.join_type == "soldiers":
                return {"soldiers": 0, "dragons": 0, "scorpions": 0}
            else:
                ratio = (ally.soldiers / side_total_soldiers) if side_total_soldiers > 0 else 0
                return {
                    "soldiers": math.floor(side_soldiers_lost * ratio),
                    "dragons": ally.dragons,
                    "scorpions": ally.scorpions,
                }
        else:
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
    loot_gold     = math.ceil(defender_gold                 * settings.WAR_LOOT_PERCENT) if attacker_wins else 0
    loot_soldiers = math.ceil(defender_house.total_soldiers * settings.WAR_LOOT_PERCENT) if attacker_wins else 0
    loot_dragons  = math.ceil(defender_house.total_dragons  * settings.WAR_LOOT_PERCENT) if attacker_wins else 0

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
