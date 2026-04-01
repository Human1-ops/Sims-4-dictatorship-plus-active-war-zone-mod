import sims4.commands
import sims4.resources

import sims4.log

logger = sims4.log.Logger('DictatorshipMod', default_level=sims4.log.LogLevel.DEBUG)

# Helper to avoid import errors at load time
def _get_services():
    import services
    return services

def _find_sim_by_name(first_name="", last_name=""):
    first_name = first_name.lower()
    last_name = last_name.lower()
    services = _get_services()
    for sim_info in services.sim_info_manager().values():
        if sim_info.first_name.lower() == first_name and sim_info.last_name.lower() == last_name:
            return sim_info
    return None

# --- Initialization Check ---
@sims4.commands.Command("dictator.ping", command_type=sims4.commands.CommandType.Live)
def _dictator_ping(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    output("Pong! The Dictatorship Mod has loaded successfully and is running.")
    return True

# --- Mod State ---
current_dictator_id = None
active_rules = set()
jailed_sims = {}  # {sim_id: alarm_handle}
active_training_deployment = None  # {sim_id}
_traveling_to_force_war = False
teen_households_granted = set()  # {household_id}
dictator_reputation = 0  # Ranges from positive (beloved) to negative (hated)
drafted_sims = {}  # {sim_id: alarm_handle}
active_war_zones = set()  # {region_id}
military_allegiances = {}  # {sim_id: "dictatorship" or "independence"}
war_ticker_alarm = None

# Core Skill IDs for max check
SKILLS_INFANT = [280058, 280061]  # Usually max at level 3
SKILLS_TODDLER = [140170, 140706, 136140, 144913, 140504]  # Most max at 5, potty at 3
SKILLS_CHILD = [16718, 16719, 16720, 16721]  # Max at 10

# Constants
FIGHT_INTERACTION_ID = 14243
MILITARY_CAREER_TRACK_ID = 202483
SURVIVED_WAR_BUFF_ID = 156158

def _has_maxed_skills(sim_info):

    from sims.sim_info_types import Age

    services = _get_services()
    skill_manager = services.get_instance_manager(sims4.resources.Types.STATISTIC)

    if sim_info.age == Age.INFANT:
        required_skills = SKILLS_INFANT
    elif sim_info.age == Age.TODDLER:
        required_skills = SKILLS_TODDLER
    elif sim_info.age == Age.CHILD:
        required_skills = SKILLS_CHILD
    else:
        return False

    stat_tracker = sim_info.statistic_tracker
    if stat_tracker is None:
        return False

    for skill_id in required_skills:
        skill_tuning = skill_manager.get(skill_id)
        if skill_tuning is None:
            continue

        stat_inst = stat_tracker.get_statistic(skill_tuning)
        if stat_inst is None:
            return False
        if stat_inst.get_user_value() < skill_tuning.max_level:
            return False

    return True

def _get_reputation_title():
    global dictator_reputation
    if dictator_reputation >= 50:
        return "Beloved Leader"
    elif dictator_reputation >= 20:
        return "Respected Authority"
    elif dictator_reputation >= -20:
        return "Controversial Figure"
    elif dictator_reputation >= -50:
        return "Feared Tyrant"
    else:
        return "Despised Despot"

@sims4.commands.Command("dictator.check_reputation", command_type=sims4.commands.CommandType.Live)
def check_reputation(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    global current_dictator_id, dictator_reputation

    if current_dictator_id is None:
        output("There is no Dictator currently in power to check reputation.")
        return False

    dictator_info = _get_services().sim_info_manager().get(current_dictator_id)
    if dictator_info is None:
        output("Dictator not found in the world.")
        return False

    title = _get_reputation_title()
    output(f"{dictator_info.full_name}'s Current Reputation: {dictator_reputation} ({title})")
    return True

@sims4.commands.Command("dictator.make_dictator", command_type=sims4.commands.CommandType.Live)
def make_dictator(first_name="", last_name="", _connection=None):
    output = sims4.commands.CheatOutput(_connection)

    target_info = _find_sim_by_name(first_name, last_name)
    if target_info is None:
        output("No target found. Make sure you typed the exact First and Last name.")
        return False

    global current_dictator_id, dictator_reputation
    current_dictator_id = target_info.id
    dictator_reputation = 0
    output(f"{target_info.full_name} is now the Dictator! Their reign begins with a neutral reputation.")
    return True

@sims4.commands.Command("dictator.die", command_type=sims4.commands.CommandType.Live)
def dictator_die(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    global current_dictator_id

    if current_dictator_id is None:
        output("There is no Dictator to die.")
        return False

    services = _get_services()
    sim_info_manager = services.sim_info_manager()
    dictator_info = sim_info_manager.get(current_dictator_id)

    if dictator_info is None:
        output("The Dictator could not be found.")
        current_dictator_id = None
        return False

    output(f"Tragedy strikes! The Dictator, {dictator_info.full_name}, has died.")

    heir_found = False
    try:
        if dictator_info.genealogy is not None:
            children_ids = dictator_info.genealogy.get_children_sim_ids()
            if children_ids:
                for child_id in children_ids:
                    heir_info = sim_info_manager.get(child_id)
                    if heir_info is not None:
                        current_dictator_id = child_id
                        output(f"Succession! {heir_info.full_name} is now the new Dictator!")
                        heir_found = True
                        break
    except Exception as e:
        output(f"Error checking genealogy: {e}")

    if not heir_found:
        output("The Dictator had no heirs. The regime has fallen!")
        current_dictator_id = None

    dictator_sim = dictator_info.get_sim_instance()
    if dictator_sim is not None:
        dictator_sim.destroy()

    return True

@sims4.commands.Command("dictator.set_rule", command_type=sims4.commands.CommandType.Live)
def set_rule(rule_name="", _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    global current_dictator_id, active_rules, dictator_reputation

    if current_dictator_id is None:
        output("There is no Dictator to set rules.")
        return False

    if not rule_name:
        output("Please specify a rule name (e.g., no_dancing).")
        return False

    active_rules.add(rule_name.lower())
    dictator_reputation -= 5
    output(f"The Dictator has decreed a new rule: {rule_name.upper()}! (Reputation -5)")
    return True

@sims4.commands.Command("dictator.remove_rule", command_type=sims4.commands.CommandType.Live)
def remove_rule(rule_name="", _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    global current_dictator_id, active_rules, dictator_reputation

    if current_dictator_id is None:
        output("There is no Dictator to remove rules.")
        return False

    rule_name = rule_name.lower()
    if rule_name in active_rules:
        active_rules.remove(rule_name)
        dictator_reputation += 5
        output(f"The Dictator has revoked the rule: {rule_name.upper()}! (Reputation +5)")
        return True
    else:
        output(f"Rule '{rule_name}' is not currently active.")
        return False

def _find_military_sim(target_id):
    sim_info_manager = _get_services().sim_info_manager()
    military_sim = None
    fallback_sim = None

    for sim_info in sim_info_manager.values():
        if sim_info.id == target_id or sim_info.id == current_dictator_id:
            continue

        sim_instance = sim_info.get_sim_instance()
        if sim_instance is None:
            continue

        if sim_info.career_tracker is not None:
            for career_uid, career in sim_info.career_tracker.careers.items():
                if career_uid == MILITARY_CAREER_TRACK_ID:
                    military_sim = sim_instance
                    break

        if fallback_sim is None:
            fallback_sim = sim_instance
        if military_sim is not None:
            break

    return military_sim if military_sim is not None else fallback_sim

@sims4.commands.Command("dictator.break_rule", command_type=sims4.commands.CommandType.Live)
def break_rule(rule_name="", first_name="", last_name="", _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    import random
    import alarms
    import date_and_time


    target_info = _find_sim_by_name(first_name, last_name)
    if target_info is None:
        output("No target found to break the rule. Provide First and Last name.")
        return False

    target_sim = target_info.get_sim_instance()
    if target_sim is None:
        output(f"{target_info.full_name} must be physically on the lot to break a rule and be punished!")
        return False

    global current_dictator_id, active_rules

    if current_dictator_id is None:
        output("There is no Dictator, so there are no rules to break.")
        return False

    if target_info.id == current_dictator_id:
        output("The Dictator is above the law!")
        return False

    rule_name = rule_name.lower()
    if rule_name not in active_rules:
        output(f"There is no rule against '{rule_name}'.")
        return False

    output(f"Oh no! {target_sim.full_name} broke the rule: {rule_name.upper()}!")

    enforcer_sim = _find_military_sim(target_sim.id)

    if enforcer_sim is None:
        output("No Military personnel could be found to enforce the rule right now.")
        return True

    output(f"The Military ({enforcer_sim.full_name}) is engaging {target_sim.full_name} in combat!")

    try:
        interaction_manager = _get_services().get_instance_manager(sims4.resources.Types.INTERACTION)
        fight_interaction = interaction_manager.get(FIGHT_INTERACTION_ID)

        if fight_interaction is not None:
            import interactions.context
            import interactions.priority
            context = interactions.context.InteractionContext(enforcer_sim, interactions.context.InteractionContext.SOURCE_SCRIPT, interactions.priority.Priority.High)
            enforcer_sim.push_super_affordance(fight_interaction, target_sim, context)
            output(f"*** {enforcer_sim.full_name} initiated a fight with {target_sim.full_name}! ***")

            def _resolve_fight_arrest(_):
                if random.random() < 0.70:
                    sims4.commands.output(f"{enforcer_sim.full_name} subdued {target_sim.full_name}! They are being sent to jail for 2 days for breaking the rule.", sims4.commands.CheatOutput(_connection=None))
                    time_span = date_and_time.create_time_span(days=2)
                    alarm_handle = alarms.add_alarm(target_sim.sim_info, time_span, lambda _: _release_from_jail(target_sim.id))
                    jailed_sims[target_sim.id] = alarm_handle
                    target_sim.destroy()
                else:
                    sims4.commands.output(f"{target_sim.full_name} managed to escape the Military after the fight! They remain free.", sims4.commands.CheatOutput(_connection=None))

            time_span = date_and_time.create_time_span(minutes=30)
            alarms.add_alarm(_get_services().current_zone(), time_span, _resolve_fight_arrest)

        else:
            output("Error: Could not load the fight interaction data.")
    except Exception as e:
        output(f"Error pushing fight interaction: {e}")

    return True

@sims4.commands.Command("dictator.arrest", command_type=sims4.commands.CommandType.Live)
def arrest_sim(first_name="", last_name="", _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    import alarms
    import date_and_time

    target_info = _find_sim_by_name(first_name, last_name)
    if target_info is None:
        output("No target found to arrest. Provide First and Last name.")
        return False

    global current_dictator_id, jailed_sims, dictator_reputation

    if current_dictator_id is None:
        output("There is no Dictator to issue an arrest warrant.")
        return False

    if target_info.id == current_dictator_id:
        output("The Dictator cannot be arrested!")
        return False

    dictator_reputation -= 15
    output(f"By decree of the Dictator, {target_info.full_name} has been arrested and sent to jail for 3 Sim days! (Reputation -15)")

    time_span = date_and_time.create_time_span(days=3)
    alarm_handle = alarms.add_alarm(target_info, time_span, lambda _: _release_from_jail(target_info.id))
    jailed_sims[target_info.id] = alarm_handle

    target_sim = target_info.get_sim_instance()
    if target_sim is not None:
        target_sim.destroy()
    return True

@sims4.commands.Command("dictator.banish", command_type=sims4.commands.CommandType.Live)
def banish(first_name="", last_name="", _connection=None):
    output = sims4.commands.CheatOutput(_connection)

    target_info = _find_sim_by_name(first_name, last_name)
    global current_dictator_id, dictator_reputation

    if target_info is None:
        output("No target found. Provide First and Last name.")
        return False

    if target_info.id == current_dictator_id:
        output("You cannot banish the Dictator!")
        return False

    dictator_reputation -= 20
    output(f"{target_info.full_name} has been banished by the Dictator! (Reputation -20)")

    target_sim = target_info.get_sim_instance()
    if target_sim is not None:
        target_sim.destroy()
    return True

@sims4.commands.Command("dictator.demand_taxes", command_type=sims4.commands.CommandType.Live)
def demand_taxes(amount=1000, _connection=None):
    output = sims4.commands.CheatOutput(_connection)

    try:
        amount = int(amount)
    except ValueError:
        output("Please provide a valid number for the amount of taxes.")
        return False

    global current_dictator_id, dictator_reputation
    if current_dictator_id is None:
        output("There is no Dictator to demand taxes.")
        return False

    dictator_info = _get_services().sim_info_manager().get(current_dictator_id)
    if dictator_info is None:
        output("Dictator not found in the world.")
        return False

    household = dictator_info.household
    if household is None:
        output("Dictator's household not found.")
        return False

    household.funds.add(amount, 0, None)
    dictator_reputation -= 10
    output(f"The Dictator has demanded and received {amount} Simoleons in taxes! The citizens grow restless. (Reputation -10)")
    return True

@sims4.commands.Command("dictator.set_allegiance", command_type=sims4.commands.CommandType.Live)
def set_allegiance(allegiance="", first_name="", last_name="", _connection=None):
    output = sims4.commands.CheatOutput(_connection)

    target_info = _find_sim_by_name(first_name, last_name)
    global military_allegiances

    if target_info is None:
        output("No target found to set allegiance. Provide First and Last name.")
        return False

    allegiance = allegiance.lower()
    if allegiance not in ["dictatorship", "independence"]:
        output("Allegiance must be either 'dictatorship' or 'independence'.")
        return False

    military_allegiances[target_info.id] = allegiance
    output(f"{target_info.full_name}'s allegiance has been set to: {allegiance.upper()}!")
    return True

# --- War System ---

def _get_all_regions():

    region_manager = _get_services().get_instance_manager(sims4.resources.Types.REGION)
    return list(region_manager.types.values()) if region_manager else []

def _release_from_jail(sim_id):
    global jailed_sims
    sim_info_manager = _get_services().sim_info_manager()
    sim_info = sim_info_manager.get(sim_id)

    if sim_id in jailed_sims:
        del jailed_sims[sim_id]

    if sim_info is not None:
        sims4.commands.output(f"{sim_info.full_name} has served their jail sentence and is released.", sims4.commands.CheatOutput(_connection=None))

def _war_ticker_callback(_):
    simulate_trait_impacts()
    import random
    global active_war_zones, current_dictator_id, dictator_reputation

    if current_dictator_id is None:
        if active_war_zones and random.random() < 0.5:
            active_war_zones.pop()
            sims4.commands.output("With the regime gone, peace returns to a former war zone.", sims4.commands.CheatOutput(_connection=None))
        return

    if random.random() < 0.05:
        _trigger_scandal_internal()

    regions = _get_all_regions()
    if not regions:
        return

    if random.random() < 0.10:
        target_region = random.choice(regions)
        if target_region.guid64 not in active_war_zones:
            active_war_zones.add(target_region.guid64)
            sims4.commands.output(f"BREAKING NEWS: War has broken out in {target_region.__name__}!", sims4.commands.CheatOutput(_connection=None))

    wars_to_end = [region_id for region_id in list(active_war_zones) if random.random() < 0.15]

    for region_id in wars_to_end:
        active_war_zones.remove(region_id)
        sims4.commands.output("A ceasefire has been declared in one of the active war zones.", sims4.commands.CheatOutput(_connection=None))

    current_zone = _get_services().current_zone()
    current_region_id = None
    if current_zone is not None:
        current_region = current_zone.region
        if current_region is not None:
            current_region_id = current_region.guid64
            if current_region_id in active_war_zones:
                _trigger_active_war_skirmish()

    _simulate_offscreen_wars(current_region_id)

    # 15% chance to trigger an autonomous training deployment (similar to an active career day)
    if random.random() < 0.15:
        _trigger_autonomous_training_deployment()

def _simulate_offscreen_wars(active_region_id):
    import random
    import alarms
    import date_and_time
    global active_war_zones, current_dictator_id, drafted_sims

    if current_dictator_id is None:
        return

    offscreen_wars = [r_id for r_id in active_war_zones if r_id != active_region_id]
    if not offscreen_wars:
        return

    sim_info_manager = _get_services().sim_info_manager()
    available_military = []

    for sim_info in sim_info_manager.values():
        if sim_info.id == current_dictator_id:
            continue
        if sim_info.id in drafted_sims:
            continue
        if sim_info.get_sim_instance() is not None:
            continue

        if sim_info.career_tracker is not None:
            for career_uid, career in sim_info.career_tracker.careers.items():
                if career_uid == MILITARY_CAREER_TRACK_ID:
                    available_military.append(sim_info)
                    break

    if not available_military:
        return

    for war_id in offscreen_wars:
        if random.random() < 0.50 and available_military:
            num_to_deploy = min(len(available_military), random.randint(1, 2))

            for _ in range(num_to_deploy):
                deploy_sim = random.choice(available_military)
                available_military.remove(deploy_sim)

                deploy_duration = random.randint(1, 3)
                sims4.commands.output(f"DEPLOYMENT: {deploy_sim.full_name} has been deployed to a war in another region for {deploy_duration} days.", sims4.commands.CheatOutput(_connection=None))

                time_span = date_and_time.create_time_span(days=deploy_duration)
                alarm_handle = alarms.add_alarm(deploy_sim, time_span, lambda _, s_id=deploy_sim.id: _return_from_war(s_id))
                drafted_sims[deploy_sim.id] = alarm_handle

def _trigger_autonomous_training_deployment():
    import random
    global current_dictator_id, active_training_deployment

    if current_dictator_id is None:
        return

    services = _get_services()
    sim_info_manager = services.sim_info_manager()
    available_military = []

    for sim_info in sim_info_manager.values():
        if sim_info.id == current_dictator_id:
            continue
        if sim_info.id in drafted_sims:
            continue

        # Only select Sims that are currently active/instantiated
        if sim_info.get_sim_instance() is None:
            continue

        if sim_info.career_tracker is not None:
            for career_uid, career in sim_info.career_tracker.careers.items():
                if career_uid == MILITARY_CAREER_TRACK_ID:
                    available_military.append(sim_info)
                    break

    if not available_military:
        return

    target_sim_info = random.choice(available_military)
    target_sim = target_sim_info.get_sim_instance()

    if target_sim is None:
        return

    current_zone_id = services.current_zone_id()
    all_zones = services.get_persistence_service().get_save_game_data_proto().zones

    valid_destinations = [z.zone_id for z in all_zones if z.zone_id != current_zone_id]

    if not valid_destinations:
        return

    destination_zone_id = random.choice(valid_destinations)

    import sims4.commands
    sims4.commands.output(f"ACTIVE DUTY: {target_sim.full_name} is being autonomously deployed to a foreign region for active training! Loading screen incoming...", sims4.commands.CheatOutput(_connection=None))

    active_training_deployment = target_sim.id

    client = services.client_manager().get_first_client()
    if client is not None:
        active_household = client.household
        if active_household is not None:
            travel_sim_ids = list(active_household.sim_ids)
            if target_sim.id not in travel_sim_ids:
                travel_sim_ids.append(target_sim.id)
            services.get_zone_situation_manager()._travel_to_zone(destination_zone_id, travel_sim_ids)

def _trigger_active_war_skirmish():
    global current_dictator_id, military_allegiances, active_war_zones

    sims4.commands.output("WARNING: The active neighborhood is a WAR ZONE! A skirmish has erupted!", sims4.commands.CheatOutput(_connection=None))

    try:
        from sims.sim_spawner import SimSpawner
        from sims.sim_info_types import Age
        import random
        import alarms
        import date_and_time
        import interactions.context
        import interactions.priority


        services = _get_services()
        sim_info_manager = services.sim_info_manager()

        military_sims_by_age = {Age.TODDLER: [], Age.CHILD: [], Age.TEEN: [], Age.YOUNGADULT: [], Age.ADULT: []}
        total_military_sims = 0

        for sim_info in sim_info_manager.values():
            if sim_info.id == current_dictator_id:
                continue
            if sim_info.age not in military_sims_by_age:
                continue
            if sim_info.get_sim_instance() is not None:
                continue

            is_military = False
            if sim_info.id in drafted_sims:
                is_military = True
            if not is_military and sim_info.age in (Age.TEEN, Age.YOUNGADULT, Age.ADULT) and sim_info.career_tracker is not None:
                for career_uid, career in sim_info.career_tracker.careers.items():
                    if career_uid == MILITARY_CAREER_TRACK_ID:
                        is_military = True
                        break

            if is_military:
                military_sims_by_age[sim_info.age].append(sim_info)
                total_military_sims += 1

        fighters_to_spawn = min(total_military_sims, random.randint(2, 4))
        spawned_fighters = []

        if fighters_to_spawn > 0:
            sims4.commands.output(f"{fighters_to_spawn} Military forces are arriving on the lot to engage in combat!", sims4.commands.CheatOutput(_connection=None))
            for i in range(fighters_to_spawn):
                available_ages = [age for age, sims in military_sims_by_age.items() if len(sims) > 0]
                if not available_ages:
                    break

                chosen_age = random.choice(available_ages)
                sim_info_to_spawn = random.choice(military_sims_by_age[chosen_age])
                military_sims_by_age[chosen_age].remove(sim_info_to_spawn)

                if sim_info_to_spawn.id not in military_allegiances:
                    allegiance = random.choice(["dictatorship", "independence"])
                    military_allegiances[sim_info_to_spawn.id] = allegiance

                allegiance = military_allegiances[sim_info_to_spawn.id]
                role_name = "Loyalist" if allegiance == "dictatorship" else "Rebel"
                sims4.commands.output(f"A {role_name} soldier ({sim_info_to_spawn.full_name}) has joined the skirmish!", sims4.commands.CheatOutput(_connection=None))

                SimSpawner.spawn_sim(sim_info_to_spawn, sim_position=None)
                spawned_fighters.append(sim_info_to_spawn)

            def push_combat_interactions(_):
                interaction_manager = services.get_instance_manager(sims4.resources.Types.INTERACTION)
                fight_interaction = interaction_manager.get(FIGHT_INTERACTION_ID)
                if fight_interaction is None:
                    return

                valid_targets = [sim for sim in services.object_manager().get_valid_objects_gen() if sim.is_sim and sim.id != current_dictator_id]
                if not valid_targets:
                    return

                for fighter_info in spawned_fighters:
                    fighter_sim = fighter_info.get_sim_instance()
                    if fighter_sim is not None:
                        fighter_allegiance = military_allegiances.get(fighter_info.id)
                        opposing_targets = [sim for sim in valid_targets if sim.id != fighter_sim.id and military_allegiances.get(sim.id) is not None and military_allegiances.get(sim.id) != fighter_allegiance]

                        if opposing_targets:
                            victim = random.choice(opposing_targets)
                        else:
                            victim = random.choice([sim for sim in valid_targets if sim.id != fighter_sim.id])

                        if victim.id != fighter_sim.id:
                            context = interactions.context.InteractionContext(fighter_sim, interactions.context.InteractionContext.SOURCE_SCRIPT, interactions.priority.Priority.High)
                            fighter_sim.push_super_affordance(fight_interaction, victim, context)
                            sims4.commands.output(f"*** {fighter_sim.full_name} is engaging {victim.full_name} in combat! ***", sims4.commands.CheatOutput(_connection=None))

            time_span = date_and_time.create_time_span(minutes=10)
            alarms.add_alarm(services.current_zone(), time_span, push_combat_interactions)
        else:
            sims4.commands.output("No off-lot Military Sims found to spawn for the skirmish.", sims4.commands.CheatOutput(_connection=None))
    except Exception as e:
        sims4.commands.output(f"Error running pure script skirmish: {e}", sims4.commands.CheatOutput(_connection=None))

    dictatorship_forces = 0
    independence_forces = 0

    services = _get_services()
    for sim in services.object_manager().get_valid_objects_gen():
        if sim.is_sim:
            allegiance = military_allegiances.get(sim.id)
            if allegiance == "dictatorship":
                dictatorship_forces += 1
            elif allegiance == "independence":
                independence_forces += 1

    if independence_forces > 0:
        sims4.commands.output(f"REBELLION: {independence_forces} rebel forces are fighting for independence on the lot!", sims4.commands.CheatOutput(_connection=None))
    if dictatorship_forces > 0:
        sims4.commands.output(f"ENFORCEMENT: {dictatorship_forces} loyalist forces are suppressing the uprising!", sims4.commands.CheatOutput(_connection=None))

    import random
    import alarms
    import date_and_time
    casualty_chance = 0.30

    if independence_forces > dictatorship_forces:
        casualty_chance += 0.20
        if random.random() < 0.40:
            current_zone = services.current_zone()
            if current_zone and current_zone.region and current_zone.region.guid64 in active_war_zones:
                active_war_zones.remove(current_zone.region.guid64)
                sims4.commands.output(f"VICTORY! The independence fighters have liberated {current_zone.region.__name__}! Peace returns.", sims4.commands.CheatOutput(_connection=None))
                return
    elif dictatorship_forces > independence_forces:
        casualty_chance += 0.40
        sims4.commands.output("The loyalist forces are showing no mercy.", sims4.commands.CheatOutput(_connection=None))
    elif independence_forces > 0 and independence_forces == dictatorship_forces:
        casualty_chance += 0.50
        sims4.commands.output("It's a chaotic stalemate between loyalists and rebels!", sims4.commands.CheatOutput(_connection=None))

    if random.random() < casualty_chance:
        valid_victims = []
        for sim in services.object_manager().get_valid_objects_gen():
            if sim.is_sim and sim.id != current_dictator_id:
                if dictatorship_forces > independence_forces and military_allegiances.get(sim.id) == "independence":
                    valid_victims.extend([sim, sim])
                elif independence_forces > dictatorship_forces and military_allegiances.get(sim.id) == "dictatorship":
                    valid_victims.extend([sim, sim])
                else:
                    valid_victims.append(sim)

        if valid_victims:
            victim = random.choice(valid_victims)
            sims4.commands.output(f"Oh no! {victim.full_name} was caught in the crossfire of the skirmish!", sims4.commands.CheatOutput(_connection=None))
            death_chance = 0.1 + (0.1 if casualty_chance > 0.5 else 0.0)
            if random.random() < death_chance:
                sims4.commands.output(f"Tragically, {victim.full_name} did not survive.", sims4.commands.CheatOutput(_connection=None))
                victim.destroy()
            else:
                sims4.commands.output(f"{victim.full_name} was injured and evacuated.", sims4.commands.CheatOutput(_connection=None))
                time_span = date_and_time.create_time_span(days=1)
                alarm_handle = alarms.add_alarm(victim.sim_info, time_span, lambda _: _release_from_jail(victim.id))
                jailed_sims[victim.id] = alarm_handle
                victim.destroy()


def _start_training_regimen(sim_id):

    import interactions.priority
    import interactions.context

    sim_info = _get_services().sim_info_manager().get(sim_id)
    if sim_info is None:
        return

    sim_instance = sim_info.get_sim_instance()
    if sim_instance is None:
        return

    interaction_manager = _get_services().get_instance_manager(sims4.resources.Types.INTERACTION)

    PUSHUPS_ID = 14238
    JOG_ID = 13444
    CHAT_ID = 26053

    pushups_sa = interaction_manager.get(PUSHUPS_ID)
    jog_sa = interaction_manager.get(JOG_ID)
    chat_sa = interaction_manager.get(CHAT_ID)

    context = interactions.context.InteractionContext(sim_instance, interactions.context.InteractionContext.SOURCE_SCRIPT, interactions.priority.Priority.High)

    sims4.commands.output(f"MILITARY TRAINING: {sim_info.full_name} has arrived and is beginning their training regimen (Pushups, Jogging, Interrogating Locals).", sims4.commands.CheatOutput(_connection=None))

    if pushups_sa is not None:
        sim_instance.push_super_affordance(pushups_sa, None, context)
    if jog_sa is not None:
        sim_instance.push_super_affordance(jog_sa, None, context)

    if chat_sa is not None:
        from sims.sim_info_types import Age
        import random
        valid_targets = [sim for sim in _get_services().object_manager().get_valid_objects_gen() if sim.is_sim and sim.id != sim_id and sim.sim_info.age in (Age.TEEN, Age.YOUNGADULT, Age.ADULT, Age.ELDER)]
        if valid_targets:
            local_sim = random.choice(valid_targets)
            sim_instance.push_super_affordance(chat_sa, local_sim, context)

def _return_from_war(sim_id):
    global drafted_sims

    import random

    sim_info_manager = _get_services().sim_info_manager()
    sim_info = sim_info_manager.get(sim_id)

    if sim_id in drafted_sims:
        del drafted_sims[sim_id]

    if sim_info is not None:
        if random.random() < 0.8:
            sims4.commands.output(f"HEROIC RETURN: {sim_info.full_name} has survived the war and returned home! They have been awarded the Medal of Valor for their efforts.", sims4.commands.CheatOutput(_connection=None))
            buff_manager = _get_services().get_instance_manager(sims4.resources.Types.BUFF)
            survived_buff = buff_manager.get(SURVIVED_WAR_BUFF_ID)

            if survived_buff is not None:
                sim_info.add_buff_from_op(survived_buff.buff_type)
                sims4.commands.output(f"*** {sim_info.full_name} received a positive moodlet for surviving! ***", sims4.commands.CheatOutput(_connection=None))
        else:
            sims4.commands.output(f"Tragic news... {sim_info.full_name} was killed in action during the war.", sims4.commands.CheatOutput(_connection=None))
            sim_instance = sim_info.get_sim_instance()
            if sim_instance is not None:
                sim_instance.destroy()

def _trigger_scandal_internal(_connection=None):
    global current_dictator_id, dictator_reputation
    if current_dictator_id is None:
        return False
    import random

    scandals = [
        "Embezzlement from the state treasury!",
        "Secret dealings with rebel forces uncovered!",
        "Inappropriate behavior caught on tape!",
        "Rigged neighborhood voting scandal!",
        "Stolen military supplies sold on the black market!",
    ]
    scandal_desc = random.choice(scandals)

    dictator_reputation -= 40
    sims4.commands.output(f"SCANDAL! The Dictator's reputation has plummeted following a shocking revelation: {scandal_desc} (Reputation -40)", sims4.commands.CheatOutput(_connection=_connection))
    return True

@sims4.commands.Command("dictator.trigger_scandal", command_type=sims4.commands.CommandType.Live)
def trigger_scandal(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    global current_dictator_id
    if current_dictator_id is None:
        output("There is no Dictator currently in power to have a scandal.")
        return False
    _trigger_scandal_internal(_connection)
    return True

@sims4.commands.Command("dictator.declare_war", command_type=sims4.commands.CommandType.Live)
def declare_war(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    global current_dictator_id, active_war_zones, dictator_reputation
    import random

    if current_dictator_id is None:
        output("There is no Dictator to declare war.")
        return False

    regions = _get_all_regions()
    if not regions:
        output("No regions found to declare war on.")
        return False

    available_regions = [r for r in regions if r.guid64 not in active_war_zones]

    if not available_regions:
        output("The entire world is already engulfed in war!")
        return False

    target_region = random.choice(available_regions)
    active_war_zones.add(target_region.guid64)
    dictator_reputation -= 30
    output(f"The Dictator has declared WAR on {target_region.__name__}! (Reputation -30)")

    current_zone = _get_services().current_zone()
    if current_zone is not None and current_zone.region is not None and current_zone.region.guid64 == target_region.guid64:
        _trigger_active_war_skirmish()

    return True

@sims4.commands.Command("dictator.travel_to_war", command_type=sims4.commands.CommandType.Live)
def travel_to_war(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    global current_dictator_id, active_war_zones
    import random

    if current_dictator_id is None:
        output("There is no Dictator to travel.")
        return False

    services = _get_services()
    current_zone_id = services.current_zone_id()
    current_zone = services.current_zone()
    current_region_id = current_zone.region.guid64 if (current_zone and current_zone.region) else None

    offscreen_wars = [r_id for r_id in active_war_zones if r_id != current_region_id]

    if not offscreen_wars:
        output("There are no active wars happening in other regions to travel to.")
        return False

    random.choice(offscreen_wars)

    all_zones = services.get_persistence_service().get_save_game_data_proto().zones
    valid_destinations = [z.zone_id for z in all_zones if z.zone_id != current_zone_id]

    if not valid_destinations:
        output("Could not find another zone to travel to.")
        return False

    destination_zone_id = random.choice(valid_destinations)
    output("The Dictator is traveling to the front lines! Loading screen incoming...")

    client = services.client_manager().get_first_client()
    if client is not None:
        active_household = client.household
        if active_household is not None:
            travel_sim_ids = list(active_household.sim_ids)
            global _traveling_to_force_war
            _traveling_to_force_war = True
            services.get_zone_situation_manager()._travel_to_zone(destination_zone_id, travel_sim_ids)

    return True

@sims4.commands.Command("dictator.deploy_training", command_type=sims4.commands.CommandType.Live)
def deploy_training(first_name="", last_name="", _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    import random

    target_info = _find_sim_by_name(first_name, last_name)
    global active_training_deployment

    if target_info is None:
        output("No target found for training deployment. Provide First and Last name.")
        return False

    target_sim = target_info.get_sim_instance()
    if target_sim is None:
        output(f"{target_info.full_name} must be physically on the lot to be deployed for training.")
        return False

    services = _get_services()
    current_zone_id = services.current_zone_id()
    all_zones = services.get_persistence_service().get_save_game_data_proto().zones

    valid_destinations = [z.zone_id for z in all_zones if z.zone_id != current_zone_id]

    if not valid_destinations:
        output("Could not find another zone to travel to for training.")
        return False

    destination_zone_id = random.choice(valid_destinations)

    output(f"Deploying {target_sim.full_name} to a foreign region for active training! Loading screen incoming...")
    active_training_deployment = target_sim.id

    client = services.client_manager().get_first_client()
    if client is not None:
        active_household = client.household
        if active_household is not None:
            travel_sim_ids = list(active_household.sim_ids)
            if target_sim.id not in travel_sim_ids:
                travel_sim_ids.append(target_sim.id)
            services.get_zone_situation_manager()._travel_to_zone(destination_zone_id, travel_sim_ids)

    return True

@sims4.commands.Command("dictator.draft_sim", command_type=sims4.commands.CommandType.Live)
def draft_sim(first_name="", last_name="", _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    import random
    import alarms
    import date_and_time
    from sims.sim_info_types import Age

    target_info = _find_sim_by_name(first_name, last_name)
    global current_dictator_id, drafted_sims, active_war_zones, dictator_reputation

    if current_dictator_id is None:
        output("There is no Dictator in power to declare war or draft Sims.")
        return False

    if not active_war_zones:
        output("There are no active wars! Sims cannot be drafted during peacetime.")
        return False

    if target_info is None:
        output("No target found to draft. Provide First and Last name.")
        return False

    target_sim = target_info.get_sim_instance()
    if target_sim is None:
        output(f"{target_info.full_name} must be physically on the lot to be drafted.")
        return False

    if target_info.id == current_dictator_id:
        output("The Dictator cannot draft themselves!")
        return False

    sim_info = target_sim.sim_info
    is_eligible = False

    if sim_info.age in (Age.TEEN, Age.YOUNGADULT, Age.ADULT, Age.CHILD, Age.TODDLER):
        is_eligible = True
    elif sim_info.age == Age.INFANT:
        if _has_maxed_skills(sim_info):
            is_eligible = True
            output(f"{target_sim.full_name} is an infant, but their exceptional skills qualify them for the draft!")
        else:
            output(f"{target_sim.full_name} is an infant and lacks the required maxed skills to be drafted.")
            return False
    else:
        output(f"{target_sim.full_name} is not an eligible age for the military draft.")
        return False

    if is_eligible:
        draft_duration_days = random.randint(2, 5)
        dictator_reputation -= 10
        output(f"By decree of the Dictator, {target_sim.full_name} has been drafted and sent to the warzone for {draft_duration_days} Sim days! (Reputation -10)")

        time_span = date_and_time.create_time_span(days=draft_duration_days)
        alarm_handle = alarms.add_alarm(sim_info, time_span, lambda _: _return_from_war(sim_info.id))
        drafted_sims[sim_info.id] = alarm_handle

        target_sim.destroy()
        return True

@sims4.commands.Command("dictator.hold_election", command_type=sims4.commands.CommandType.Live)
def hold_election(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    global current_dictator_id, dictator_reputation
    import random
    from sims.sim_info_types import Age

    services = _get_services()
    sim_info_manager = services.sim_info_manager()

    if current_dictator_id is None:
        client = services.client_manager().get_first_client()
        if client and client.active_sim:
            current_dictator_id = client.active_sim.id
            dictator_reputation = 0
            output(f"{client.active_sim.full_name} has stepped up to run as the Dictator candidate.")
        else:
            output("No active Sim to run for Dictator.")
            return False

    dictator_info = sim_info_manager.get(current_dictator_id)
    if dictator_info is None:
        output("Dictator candidate not found in world.")
        return False

    FAME_STAT_ID = 188229

    stat_manager = services.get_instance_manager(sims4.resources.Types.STATISTIC)
    fame_tuning = stat_manager.get(FAME_STAT_ID)

    celebrity_politician = None
    highest_fame = -1

    for sim_info in sim_info_manager.values():
        if sim_info.id == current_dictator_id or sim_info.age not in (Age.YOUNGADULT, Age.ADULT, Age.ELDER):
            continue

        fame_val = 0
        if fame_tuning is not None and sim_info.statistic_tracker is not None:
            stat_inst = sim_info.statistic_tracker.get_statistic(fame_tuning)
            if stat_inst is not None:
                fame_val = stat_inst.get_value()

        if fame_val > highest_fame:
            highest_fame = fame_val
            celebrity_politician = sim_info

    if celebrity_politician is None:
        valid_adults = [s for s in sim_info_manager.values() if s.id != current_dictator_id and s.age in (Age.YOUNGADULT, Age.ADULT, Age.ELDER)]
        if valid_adults:
            celebrity_politician = random.choice(valid_adults)
        else:
            output("Not enough Sims in the world to hold an election.")
            return False

    output(f"ELECTION DAY: {dictator_info.full_name} (Dictatorship) vs {celebrity_politician.full_name} (Celebrity Politician)!")

    dictator_votes = 0
    politician_votes = 0

    voters = [s for s in sim_info_manager.values() if s.age in (Age.TEEN, Age.YOUNGADULT, Age.ADULT, Age.ELDER)]

    for voter in voters:
        if voter.id == current_dictator_id:
            dictator_votes += 1
            continue
        if voter.id == celebrity_politician.id:
            politician_votes += 1
            continue

        eco_footprint_score = 0
        if voter.statistic_tracker is not None:
            eco_stat = stat_manager.get(231429)
            if eco_stat is not None:
                stat_inst = voter.statistic_tracker.get_statistic(eco_stat)
                if stat_inst is not None:
                    val = stat_inst.get_value()
                    if val < -100:
                        eco_footprint_score = -1
                    elif val > 100:
                        eco_footprint_score = 1

        if eco_footprint_score == 0 and random.random() < 0.4:
            eco_footprint_score = random.choice([-1, 1])

        vote_dictator_chance = 0.50

        if dictator_reputation > 30:
            vote_dictator_chance += 0.15
        elif dictator_reputation < -30:
            vote_dictator_chance -= 0.15

        if eco_footprint_score == -1:
            vote_dictator_chance += 0.35
        elif eco_footprint_score == 1:
            vote_dictator_chance -= 0.35

        vote_dictator_chance = max(0.05, min(0.95, vote_dictator_chance))

        if random.random() < vote_dictator_chance:
            dictator_votes += 1
        else:
            politician_votes += 1

    output(f"RESULTS: {dictator_votes} votes for {dictator_info.full_name}, {politician_votes} votes for {celebrity_politician.full_name}.")

    if dictator_votes >= politician_votes:
        output("VICTORY! The Dictatorship remains in power. (Reputation +20)")
        dictator_reputation += 20
    else:
        output(f"DEFEAT! The Celebrity Politician {celebrity_politician.full_name} won the popular vote! The Dictator was overthrown.")
        current_dictator_id = None

    return True

@sims4.commands.Command("dictator.illegal_vote", command_type=sims4.commands.CommandType.Live)
def illegal_vote(first_name="", last_name="", _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    import random
    from sims.sim_info_types import Age

    target_info = _find_sim_by_name(first_name, last_name)
    global current_dictator_id

    if current_dictator_id is None:
        output("There is no Dictator in power, so voting is allowed.")
        return True

    if target_info is None:
        output("No target found for illegal voting. Provide First and Last name.")
        return False

    target_sim = target_info.get_sim_instance()
    if target_sim is None:
        output(f"{target_info.full_name} must be physically on the lot to face consequences for illegal voting.")
        return False

    if target_sim.id == current_dictator_id:
        output("The Dictator can do whatever they want, including pretending to vote.")
        return True

    sim_info = target_sim.sim_info

    if sim_info.age in (Age.TEEN, Age.YOUNGADULT, Age.ADULT, Age.ELDER):
        output(f"{target_sim.full_name} tried to vote illegally! The Military has arrested them and sent them to jail for 3 Sim days.")
        if target_sim is not None:
            target_sim.destroy()
    elif sim_info.age in (Age.BABY, Age.INFANT, Age.TODDLER, Age.CHILD):
        household_manager = _get_services().household_manager()
        eligible_households = [hh for hh in household_manager.values() if hh.id != sim_info.household.id and hh.home_zone_id != 0 and len(list(hh.sim_info_gen())) < 8]

        if eligible_households:
            adoptive_household = random.choice(eligible_households)
            current_household = sim_info.household
            if current_household is not None:
                current_household.remove_sim_info(sim_info)
            adoptive_household.add_sim_info(sim_info)
            output(f"Because the family committed treason by trying to vote, the child {target_sim.full_name} has been taken away and adopted by the {adoptive_household.name} household!")
            if target_sim is not None:
                target_sim.destroy()
        else:
            output(f"Could not find an eligible household to adopt the child {target_sim.full_name}.")
            if target_sim is not None:
                target_sim.destroy()
    return True


# --- Injection Hooks ---

def inject_to(target_module_name, target_function_name):
    def _inject_to(new_function):
        try:
            import importlib
            target_module = importlib.import_module(target_module_name)

            # Handle nested objects (like ClassName.method_name)
            parts = target_function_name.split('.')
            target_obj = target_module
            for part in parts[:-1]:
                target_obj = getattr(target_obj, part)

            final_func_name = parts[-1]
            original_function = getattr(target_obj, final_func_name)

            def _wrapper(*args, **kwargs):
                return new_function(original_function, *args, **kwargs)

            setattr(target_obj, final_func_name, _wrapper)
            logger.debug(f"Successfully injected into {target_module_name}.{target_function_name}")
            return _wrapper
        except Exception as e:
            logger.error(f"Failed to inject into {target_module_name}.{target_function_name}: {e}")
            return new_function
    return _inject_to

@inject_to("interactions.base.super_interaction", "SuperInteraction.test")
def _super_interaction_test_override(original_function, cls, *args, **kwargs):
    result = original_function(cls, *args, **kwargs)

    if current_dictator_id is None:
        return result

    try:
        from event_testing.results import TestResult
        interaction_name = cls.__name__.lower()
        if "vote" in interaction_name or "civicpolicy" in interaction_name:
            # test() is a classmethod, so we must inspect kwargs context to find the sim
            context = kwargs.get('context')
            if context and hasattr(context, 'sim') and context.sim:
                sim_info = context.sim.sim_info
                if sim_info.sim_id == current_dictator_id:
                    return TestResult.TRUE
    except Exception as e:
        pass

    return result

@inject_to("interactions.base.super_interaction", "SuperInteraction.on_started")
def _super_interaction_on_started_hook(original_function, self, *args, **kwargs):
    original_function(self, *args, **kwargs)

    if current_dictator_id is None:
        return

    try:
        import random
        interaction_name = self.__class__.__name__.lower()
        if "vote" in interaction_name or "civicpolicy" in interaction_name:
            sim_info = self.sim.sim_info

            # The dictator is exempt.
            if sim_info.sim_id == current_dictator_id:
                return

            # Otherwise, they are risking an illegal vote! 30% chance of getting caught!
            if random.random() < 0.30:
                import sims4.commands
                # We trigger the same logic as the dictator.illegal_vote command!
                sims4.commands.client_cheat(f"dictator.illegal_vote \"{sim_info.first_name}\" \"{sim_info.last_name}\"", None)
    except Exception as e:
        pass

@inject_to("zone", "Zone.do_zone_spin_up")
def _hook_zone_spin_up(original_function, self, *args, **kwargs):
    result = original_function(self, *args, **kwargs)
    import alarms
    import date_and_time

    # Aggressively inject our election interaction into all mailboxes and community boards
    # Since the zone is fully spinning up, tuning instances are guaranteed to be loaded.
    try:
        import sims4.resources
        object_manager = _get_services().get_instance_manager(sims4.resources.Types.OBJECT)
        if object_manager is not None:
            interaction_cls = _create_election_interaction()
            if interaction_cls is not None:
                for obj_tuning in object_manager.types.values():
                    class_name = getattr(obj_tuning, '__name__', '').lower()
                    # Mailboxes often have 'mailbox' in their name, but base game residential is just 'mailbox'
                    # We also inject into anything labeled community board
                    if 'mailbox' in class_name or 'communityboard' in class_name or 'civicpolicy' in class_name:
                        if hasattr(obj_tuning, '_super_affordances'):
                            affordances = list(obj_tuning._super_affordances)
                            if interaction_cls not in affordances:
                                affordances.append(interaction_cls)
                                obj_tuning._super_affordances = tuple(affordances)
    except Exception as e:
        import sims4.commands
        sims4.commands.output(f"Failed mailbox injection: {e}", sims4.commands.CheatOutput(_connection=None))

    global war_ticker_alarm, active_training_deployment
    if war_ticker_alarm is None:
        time_span = date_and_time.create_time_span(hours=6)
        war_ticker_alarm = alarms.add_alarm(self, time_span, _war_ticker_callback, repeating=True)

    if active_training_deployment is not None:
        sim_id = active_training_deployment
        active_training_deployment = None

        sim_info = _get_services().sim_info_manager().get(sim_id)
        if sim_info is not None:
            time_span = date_and_time.create_time_span(minutes=5)
            alarms.add_alarm(self, time_span, lambda _: _start_training_regimen(sim_info.id))

    global _traveling_to_force_war
    current_region = self.region if hasattr(self, "region") else None

    if _traveling_to_force_war and current_region is not None:
        active_war_zones.add(current_region.guid64)
        _traveling_to_force_war = False

    if current_region is not None and current_region.guid64 in active_war_zones:
        time_span = date_and_time.create_time_span(minutes=5)
        alarms.add_alarm(self, time_span, lambda _: _trigger_active_war_skirmish())

    global teen_households_granted, current_dictator_id
    if current_dictator_id is not None:
        try:
            from sims.sim_info_types import Age
            client = _get_services().client_manager().get_first_client()
            if client is not None and client.household is not None:
                active_hh = client.household
                if active_hh.id not in teen_households_granted:
                    all_teens = True
                    sim_count = 0
                    for sim_info in active_hh.sim_info_gen():
                        sim_count += 1
                        if sim_info.age != Age.TEEN:
                            all_teens = False
                            break

                    if all_teens and sim_count > 0:
                        active_hh.funds.add(5000, 0, None)
                        teen_households_granted.add(active_hh.id)

                        global dictator_reputation
                        dictator_reputation += 10
                        import sims4.commands
                        sims4.commands.output("DICTATORSHIP GRANT: This teen-only household has received 5,000 Simoleons to encourage independent living! The public appreciates this support. (Reputation +10)", sims4.commands.CheatOutput(_connection=None))
                    elif not all_teens:
                        teen_households_granted.add(active_hh.id)
        except Exception:
            pass

    return result

# --- Interaction Cloning ---

VIEW_INTERACTION_ID = 14454
_dictator_election_interaction = None

def _create_election_interaction():
    global _dictator_election_interaction
    if _dictator_election_interaction is not None:
        return _dictator_election_interaction

    try:
        import sims4.resources
        interaction_manager = _get_services().get_instance_manager(sims4.resources.Types.INTERACTION)
        if interaction_manager is None:
            return None
        base_interaction = interaction_manager.get(VIEW_INTERACTION_ID)

        if base_interaction is None:
            import interactions.base.super_interaction
            base_interaction = interactions.base.super_interaction.SuperInteraction

        class CustomElectionInteraction(base_interaction):
            @classmethod
            def _test(cls, target, context, **kwargs):
                global current_dictator_id
                if current_dictator_id is None or context.sim.id != current_dictator_id:
                    from event_testing.results import TestResult
                    return TestResult(False, "Only the Dictator can hold the election.")
                from event_testing.results import TestResult
                return TestResult.TRUE

            @property
            def display_name(self):
                import sims4.localization
                return sims4.localization._create_localized_string(0x61AE64E0)

            def get_name(self, target=None, context=None, **kwargs):
                import sims4.localization
                return sims4.localization._create_localized_string(0x61AE64E0)

            def _run_interaction_gen(self, timeline):
                import sims4.commands
                global current_dictator_id, dictator_reputation
                sims4.commands.output("Election interaction started from the board!", sims4.commands.CheatOutput(_connection=None))
                hold_election()
                yield True

        CustomElectionInteraction.__name__ = "DictatorshipMod_HoldElection"
        _dictator_election_interaction = CustomElectionInteraction
        return CustomElectionInteraction

    except Exception:
        return None



# ==============================================================================
# VIRTUAL TRAITS SYSTEM
# ==============================================================================
# Since full traits require XML tuning, we implement a "Virtual Trait" prototype
# where Sims are assigned a trait via Python state and receive customized
# simulated effects like buffs and relationship multipliers.

virtual_traits = {}

@sims4.commands.Command('dictator.add_trait', command_type=sims4.commands.CommandType.Live)
def add_virtual_trait(first_name="", last_name="", trait_name="", _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    try:
        sim_info = _find_sim_by_name(first_name, last_name)

        if not sim_info:
            output("Sim not found.")
            return False

        valid_traits = ['true_believer', 'paranoid', 'submissive', 'dissident', 'opportunist']
        trait_name = trait_name.lower()
        if trait_name not in valid_traits:
            output(f"Invalid trait. Choose from: {', '.join(valid_traits)}")
            return False

        sim_id_int = sim_info.sim_id

        if sim_id_int not in virtual_traits:
            virtual_traits[sim_id_int] = set()

        virtual_traits[sim_id_int].add(trait_name)
        output(f"Added virtual trait '{trait_name}' to {sim_info.first_name} {sim_info.last_name}.")
        return True
    except Exception as e:
        output(f"Error adding trait: {e}")
        return False

@sims4.commands.Command('dictator.remove_trait', command_type=sims4.commands.CommandType.Live)
def remove_virtual_trait(first_name="", last_name="", trait_name="", _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    try:
        sim_info = _find_sim_by_name(first_name, last_name)

        if not sim_info:
            output("Sim not found.")
            return False

        sim_id_int = sim_info.sim_id

        if sim_id_int in virtual_traits and trait_name.lower() in virtual_traits[sim_id_int]:
            virtual_traits[sim_id_int].remove(trait_name.lower())
            output(f"Removed virtual trait '{trait_name}' from {sim_info.first_name} {sim_info.last_name}.")
            return True
        else:
            output(f"Sim does not have trait '{trait_name}'.")
            return False
    except Exception as e:
        output(f"Error removing trait: {e}")
        return False

@sims4.commands.Command('dictator.show_traits', command_type=sims4.commands.CommandType.Live)
def show_virtual_traits(first_name="", last_name="", _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    try:
        sim_info = _find_sim_by_name(first_name, last_name)

        if not sim_info:
            output("Sim not found.")
            return False

        sim_id_int = sim_info.sim_id

        traits = virtual_traits.get(sim_id_int, set())
        if traits:
            output(f"{sim_info.first_name} {sim_info.last_name}'s traits: {', '.join(traits)}")
        else:
            output(f"{sim_info.first_name} {sim_info.last_name} has no virtual traits.")
        return True
    except Exception as e:
        output(f"Error showing traits: {e}")
        return False

# Function to simulate trait impacts over time (called during the war ticker or background processes)
def simulate_trait_impacts():
    import services

    # Base game buff IDs for prototyping moodlets
    BUFF_CONFIDENT = 12826
    BUFF_TENSE = 12850
    BUFF_BORED = 12823
    BUFF_INSPIRED = 12841
    BUFF_PLAYFUL = 12847
    BUFF_ANGRY = 12818
    BUFF_HAPPY = 12836

    for sim_id, traits in virtual_traits.items():
        sim_info = services.sim_info_manager().get(sim_id)
        if not sim_info:
            continue

        for trait in traits:
            if trait == "true_believer":
                # Gains Confident buff representing pride in regime
                try:
                    buff_type = services.get_instance_manager(sims4.resources.Types.BUFF).get(BUFF_CONFIDENT)
                    if buff_type:
                        sim_info.add_buff_from_op(buff_type)
                except Exception as e:
                    pass
            elif trait == "paranoid":
                # Gains Tense buff representing fear of informants
                try:
                    buff_type = services.get_instance_manager(sims4.resources.Types.BUFF).get(BUFF_TENSE)
                    if buff_type:
                        sim_info.add_buff_from_op(buff_type)
                except Exception as e:
                    pass
            elif trait == "submissive":
                # Removes negative work-related buffs like bored, block playful
                try:
                    for buff_id in (BUFF_BORED, BUFF_INSPIRED, BUFF_PLAYFUL):
                        buff_type = services.get_instance_manager(sims4.resources.Types.BUFF).get(buff_id)
                        if buff_type:
                            sim_info.remove_buff_by_type(buff_type)
                except Exception as e:
                    pass
            elif trait == "dissident":
                # Gains Angry buff reflecting hatred of the state
                try:
                    buff_type = services.get_instance_manager(sims4.resources.Types.BUFF).get(BUFF_ANGRY)
                    if buff_type:
                        sim_info.add_buff_from_op(buff_type)
                except Exception as e:
                    pass
            elif trait == "opportunist":
                # Gains Happy buff representing social climbing immunity
                try:
                    buff_type = services.get_instance_manager(sims4.resources.Types.BUFF).get(BUFF_HAPPY)
                    if buff_type:
                        sim_info.add_buff_from_op(buff_type)
                except Exception as e:
                    pass
