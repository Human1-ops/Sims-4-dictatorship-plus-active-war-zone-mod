import sims4.tuning.instances
import sims4.commands
import services
from sims.sim_info_types import Age
import random
import alarms
import date_and_time
import zone
from event_testing.results import TestResult
import sims4.localization


# --- Initialization Check ---
@sims4.commands.Command("dictator.ping", command_type=sims4.commands.CommandType.Live)
def _dictator_ping(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    output("Pong! The Dictatorship Mod has loaded successfully and is running.")
    return True


def _find_sim_by_name(first_name: str, last_name: str):
    """Helper to find a sim_info by first and last name from the sim_info_manager."""
    first_name = first_name.lower()
    last_name = last_name.lower()
    sim_info_manager = services.sim_info_manager()
    for sim_info in sim_info_manager.values():
        if sim_info.first_name.lower() == first_name and sim_info.last_name.lower() == last_name:
            return sim_info
    return None


# --- Mod State ---
current_dictator_id = None
active_rules = set()
jailed_sims = {}  # {sim_id: alarm_handle}
active_training_deployment = None  # {sim_id}
_traveling_to_force_war = False
teen_households_granted = set()  # {household_id}
dictator_reputation = 0  # Ranges from positive (beloved) to negative (hated)

# Core Skill IDs for max check
# Note: These are base game example IDs.
# Infant: Fine Motor (280058), Gross Motor (280061), Crawling/Walking etc.
# Toddler: Communication (140170), Imagination (140706), Movement (136140), Potty (144913), Thinking (140504)
# Child: Creativity (16718), Mental (16719), Motor (16720), Social (16721)

SKILLS_INFANT = [280058, 280061]  # Usually max at level 3
SKILLS_TODDLER = [140170, 140706, 136140, 144913, 140504]  # Most max at 5, potty at 3
SKILLS_CHILD = [16718, 16719, 16720, 16721]  # Max at 10


def _has_maxed_skills(sim_info):
    """Checks if a Sim has maxed their age-specific foundational skills."""
    import sims4.resources

    skill_manager = services.get_instance_manager(sims4.resources.Types.STATISTIC)

    if sim_info.age == Age.INFANT:
        required_skills = SKILLS_INFANT
    elif sim_info.age == Age.TODDLER:
        required_skills = SKILLS_TODDLER
    elif sim_info.age == Age.CHILD:
        required_skills = SKILLS_CHILD
    else:
        return False  # This function is only for young ages

    stat_tracker = sim_info.statistic_tracker
    if stat_tracker is None:
        return False

    for skill_id in required_skills:
        skill_tuning = skill_manager.get(skill_id)
        if skill_tuning is None:
            continue

        stat_inst = stat_tracker.get_statistic(skill_tuning)
        # If they don't even have the skill started, they haven't maxed it
        if stat_inst is None:
            return False

        # Check if their current level is equal to or greater than the max possible level for that skill
        if stat_inst.get_user_value() < skill_tuning.max_level:
            return False

    return True


drafted_sims = {}  # {sim_id: alarm_handle}
active_war_zones = set()  # {region_id}
military_allegiances = {}  # {sim_id: "dictatorship" or "independence"}
war_ticker_alarm = None

# A simplified mock of a "fight" interaction ID. In reality, you'd find the
# correct Interaction SA (Super Interaction) ID for fighting from the game files.
FIGHT_INTERACTION_ID = 14243  # Example ID, might need tuning for a real mod.
MILITARY_CAREER_TRACK_ID = 202483  # StrangerVille military career


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


@sims4.commands.Command(
    "dictator.check_reputation", command_type=sims4.commands.CommandType.Live
)
def check_reputation(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    global current_dictator_id, dictator_reputation

    if current_dictator_id is None:
        output("There is no Dictator currently in power to check reputation.")
        return False

    dictator_info = services.sim_info_manager().get(current_dictator_id)
    if dictator_info is None:
        output("Dictator not found in the world.")
        return False

    title = _get_reputation_title()
    output(
        f"{dictator_info.full_name}'s Current Reputation: {dictator_reputation} ({title})"
    )
    return True


@sims4.commands.Command(
    "dictator.make_dictator", command_type=sims4.commands.CommandType.Live
)
def make_dictator(first_name="", last_name="", _connection=None):
    output = sims4.commands.CheatOutput(_connection)

    target_info = _find_sim_by_name(first_name, last_name)
    if target_info is None:
        output("No target found. Make sure you typed the exact First and Last name.")
        return False

    global current_dictator_id, dictator_reputation
    current_dictator_id = target_info.id
    dictator_reputation = 0  # Reset reputation for the new dictator
    output(
        f"{target_info.full_name} is now the Dictator! Their reign begins with a neutral reputation."
    )
    return True


@sims4.commands.Command("dictator.die", command_type=sims4.commands.CommandType.Live)
def dictator_die(_connection=None):
    """Simulates the Dictator's death and handles succession."""
    output = sims4.commands.CheatOutput(_connection)
    global current_dictator_id

    if current_dictator_id is None:
        output("There is no Dictator to die.")
        return False

    sim_info_manager = services.sim_info_manager()
    dictator_info = sim_info_manager.get(current_dictator_id)

    if dictator_info is None:
        output("The Dictator could not be found.")
        current_dictator_id = None
        return False

    output(f"Tragedy strikes! The Dictator, {dictator_info.full_name}, has died.")

    # Handle Succession (find a child)
    heir_found = False

    # We iterate over the sim_info_manager to find a child (regardless of age)
    # The 'genealogy' attribute is commonly used to find relationships in Sims 4 scripting.
    try:
        if dictator_info.genealogy is not None:
            children_ids = dictator_info.genealogy.get_children_sim_ids()
            if children_ids:
                # Pick the first child found as the heir
                for child_id in children_ids:
                    heir_info = sim_info_manager.get(child_id)
                    if heir_info is not None:
                        current_dictator_id = child_id
                        output(
                            f"Succession! {heir_info.full_name} is now the new Dictator!"
                        )
                        heir_found = True
                        break
    except Exception as e:
        output(f"Error checking genealogy: {e}")

    if not heir_found:
        output("The Dictator had no heirs. The regime has fallen!")
        current_dictator_id = None

    # Simulate the actual death (destroy the sim object if they are instantiated)
    dictator_sim = dictator_info.get_sim_instance()
    if dictator_sim is not None:
        dictator_sim.destroy()

    return True


@sims4.commands.Command(
    "dictator.set_rule", command_type=sims4.commands.CommandType.Live
)
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


@sims4.commands.Command(
    "dictator.remove_rule", command_type=sims4.commands.CommandType.Live
)
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
        output(
            f"The Dictator has revoked the rule: {rule_name.upper()}! (Reputation +5)"
        )
        return True
    else:
        output(f"Rule '{rule_name}' is not currently active.")
        return False


def _find_military_sim(target_id):
    """Finds an instantiated Sim in the Military career.
    Falls back to any instantiated active Sim if none found."""
    sim_info_manager = services.sim_info_manager()
    military_sim = None
    fallback_sim = None

    for sim_info in sim_info_manager.values():
        if sim_info.id == target_id or sim_info.id == current_dictator_id:
            continue

        sim_instance = sim_info.get_sim_instance()
        if sim_instance is None:
            continue

        # Prioritize finding a Military Sim (StrangerVille career ID check)
        if sim_info.career_tracker is not None:
            for career_uid, career in sim_info.career_tracker.careers.items():
                if career_uid == MILITARY_CAREER_TRACK_ID:
                    military_sim = sim_instance
                    break

        # Save a fallback just in case
        if fallback_sim is None:
            fallback_sim = sim_instance

        if military_sim is not None:
            break

    return military_sim if military_sim is not None else fallback_sim


@sims4.commands.Command(
    "dictator.break_rule", command_type=sims4.commands.CommandType.Live
)
def break_rule(
    rule_name: str, first_name="", last_name="", _connection=None
):
    """Simulates a Sim breaking a rule and being punished via a physical fight."""
    output = sims4.commands.CheatOutput(_connection)

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

    output(
        f"The Military ({enforcer_sim.full_name}) is engaging {target_sim.full_name} in combat!"
    )

    # 2. Push a fight interaction
    # Fight interaction tuning ID. In base game, generic fight is often 14243.
    # We load the tuning snippet and push it onto the enforcer's queue targeting the rulebreaker.
    try:
        interaction_manager = services.get_instance_manager(
            sims4.resources.Types.INTERACTION
        )
        fight_interaction = interaction_manager.get(FIGHT_INTERACTION_ID)

        if fight_interaction is not None:
            from interactions.context import InteractionContext
            import interactions.priority

            # Create an interaction context for the enforcer.
            context = InteractionContext(
                enforcer_sim,
                InteractionContext.SOURCE_SCRIPT,
                interactions.priority.Priority.High,
            )
            # Push the interaction
            enforcer_sim.push_super_affordance(fight_interaction, target_sim, context)
            output(
                f"*** {enforcer_sim.full_name} initiated a fight with {target_sim.full_name}! ***"
            )

            # Since tracking actual interaction results (who won the fight) requires complex state listeners in Python,
            # we will simulate the outcome here via a delayed alarm. If the enforcer wins (higher chance), the target is arrested.
            def _resolve_fight_arrest(_):
                # 70% chance the military enforcer wins and arrests them
                if random.random() < 0.70:
                    sims4.commands.output(
                        f"{enforcer_sim.full_name} subdued {target_sim.full_name}! They are being sent to jail for 2 days for breaking the rule.",
                        sims4.commands.CheatOutput(_connection=None),
                    )

                    time_span = date_and_time.create_time_span(days=2)
                    alarm_handle = alarms.add_alarm(
                        target_sim.sim_info,
                        time_span,
                        lambda _: _release_from_jail(target_sim.id),
                    )
                    jailed_sims[target_sim.id] = alarm_handle
                    target_sim.destroy()
                else:
                    sims4.commands.output(
                        f"{target_sim.full_name} managed to escape the Military after the fight! They remain free.",
                        sims4.commands.CheatOutput(_connection=None),
                    )

            # Set alarm for 30 sim minutes to let the fight happen before resolving the arrest
            time_span = date_and_time.create_time_span(minutes=30)
            alarms.add_alarm(services.current_zone(), time_span, _resolve_fight_arrest)

        else:
            output("Error: Could not load the fight interaction data.")
    except Exception as e:
        output(f"Error pushing fight interaction: {e}")

    return True


@sims4.commands.Command("dictator.arrest", command_type=sims4.commands.CommandType.Live)
def arrest_sim(first_name="", last_name="", _connection=None):
    """The Dictator instantly orders the arrest of a target Sim without a fight."""
    output = sims4.commands.CheatOutput(_connection)

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
    output(
        f"By decree of the Dictator, {target_info.full_name} has been arrested and sent to jail for 3 Sim days! (Reputation -15)"
    )

    time_span = date_and_time.create_time_span(days=3)
    alarm_handle = alarms.add_alarm(
        target_info, time_span, lambda _: _release_from_jail(target_info.id)
    )
    jailed_sims[target_info.id] = alarm_handle

    # Send them to jail (despawn)
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


@sims4.commands.Command(
    "dictator.demand_taxes", command_type=sims4.commands.CommandType.Live
)
def demand_taxes(amount=1000, _connection=None):
    output = sims4.commands.CheatOutput(_connection)

    global current_dictator_id, dictator_reputation
    if current_dictator_id is None:
        output("There is no Dictator to demand taxes.")
        return False

    dictator_info = services.sim_info_manager().get(current_dictator_id)
    if dictator_info is None:
        output("Dictator not found in the world.")
        return False

    household = dictator_info.household
    if household is None:
        output("Dictator's household not found.")
        return False

    household.funds.add(amount, 0, None)
    dictator_reputation -= 10
    output(
        f"The Dictator has demanded and received {amount} Simoleons in taxes! The citizens grow restless. (Reputation -10)"
    )
    return True


@sims4.commands.Command(
    "dictator.set_allegiance", command_type=sims4.commands.CommandType.Live
)
def set_allegiance(
    allegiance: str, first_name="", last_name="", _connection=None
):
    """Sets the military allegiance of a Sim to 'dictatorship' or 'independence'."""
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
    output(
        f"{target_info.full_name}'s allegiance has been set to: {allegiance.upper()}!"
    )
    return True


# --- War System ---


def _get_all_regions():
    """Returns a list of all Region instances available in the game."""
    region_manager = services.get_instance_manager(sims4.resources.Types.REGION)
    return list(region_manager.types.values()) if region_manager else []


def _release_from_jail(sim_id):
    """Callback function when the 3-day jail alarm fires."""
    global jailed_sims
    sim_info_manager = services.sim_info_manager()
    sim_info = sim_info_manager.get(sim_id)

    if sim_id in jailed_sims:
        del jailed_sims[sim_id]

    if sim_info is not None:
        sims4.commands.output(
            f"{sim_info.full_name} has served their jail sentence and is released.",
            sims4.commands.CheatOutput(_connection=None),
        )


def _war_ticker_callback(_):
    """Fires periodically to start or end wars, trigger skirmishes, and handle random scandals."""
    global active_war_zones, current_dictator_id, dictator_reputation

    if current_dictator_id is None:
        # If the dictator dies/falls, wars slowly end.
        if active_war_zones and random.random() < 0.5:
            active_war_zones.pop()
            sims4.commands.output(
                "With the regime gone, peace returns to a former war zone.",
                sims4.commands.CheatOutput(_connection=None),
            )
        return

    # 5% chance of a random political scandal occurring every tick
    if random.random() < 0.05:
        _trigger_scandal_internal()

    regions = _get_all_regions()
    if not regions:
        return

    # Chance to start a new war (10% chance every tick)
    if random.random() < 0.10:
        target_region = random.choice(regions)
        if target_region.guid64 not in active_war_zones:
            active_war_zones.add(target_region.guid64)
            sims4.commands.output(
                f"BREAKING NEWS: War has broken out in {target_region.__name__}!",
                sims4.commands.CheatOutput(_connection=None),
            )

    # Chance to end an existing war (15% chance per tick for any given war)
    wars_to_end = []
    for region_id in list(active_war_zones):
        if random.random() < 0.15:
            wars_to_end.append(region_id)

    for region_id in wars_to_end:
        active_war_zones.remove(region_id)
        sims4.commands.output(
            "A ceasefire has been declared in one of the active war zones.",
            sims4.commands.CheatOutput(_connection=None),
        )

    # Skirmish check: Is the current active lot in a war zone?
    current_zone = services.current_zone()
    current_region_id = None
    if current_zone is not None:
        current_region = current_zone.region
        if current_region is not None:
            current_region_id = current_region.guid64
            if current_region_id in active_war_zones:
                _trigger_active_war_skirmish()

    # Simulate deployments for wars in other worlds
    _simulate_offscreen_wars(current_region_id)


def _simulate_offscreen_wars(active_region_id):
    """Pulls available military Sims to fight in wars happening in other worlds."""
    global active_war_zones, current_dictator_id, drafted_sims
    import sims4.commands

    if current_dictator_id is None:
        return

    # Get all active wars that are NOT the current zone
    offscreen_wars = [r_id for r_id in active_war_zones if r_id != active_region_id]
    if not offscreen_wars:
        return

    sim_info_manager = services.sim_info_manager()
    available_military = []

    # Find all eligible military Sims who are NOT currently drafted/deployed and NOT on the active lot
    for sim_info in sim_info_manager.values():
        if sim_info.id == current_dictator_id:
            continue

        # If they are already drafted/deployed, skip
        if sim_info.id in drafted_sims:
            continue

        # Must not be instantiated on the current lot
        if sim_info.get_sim_instance() is not None:
            continue

        if sim_info.career_tracker is not None:
            for career_uid, career in sim_info.career_tracker.careers.items():
                if career_uid == MILITARY_CAREER_TRACK_ID:
                    available_military.append(sim_info)
                    break

    if not available_military:
        return

    # For each off-screen war, there's a chance to deploy 1-2 Sims
    for war_id in offscreen_wars:
        # 50% chance to deploy someone to this war on this tick
        if random.random() < 0.50 and available_military:
            num_to_deploy = min(len(available_military), random.randint(1, 2))

            for _ in range(num_to_deploy):
                deploy_sim = random.choice(available_military)
                available_military.remove(deploy_sim)

                # Deploy them for 1 to 3 days
                deploy_duration = random.randint(1, 3)
                sims4.commands.output(
                    f"DEPLOYMENT: {deploy_sim.full_name} has been deployed to a war in another region for {deploy_duration} days.",
                    sims4.commands.CheatOutput(_connection=None),
                )

                time_span = date_and_time.create_time_span(days=deploy_duration)
                alarm_handle = alarms.add_alarm(
                    deploy_sim,
                    time_span,
                    lambda _, s_id=deploy_sim.id: _return_from_war(s_id),
                )
                drafted_sims[deploy_sim.id] = alarm_handle


def _trigger_active_war_skirmish():
    """A skirmish happens on the active lot because it's in a war zone.
    Pure script implementation (no custom XML Situations)."""
    global current_dictator_id, military_allegiances, active_war_zones
    import sims4.commands

    sims4.commands.output(
        "WARNING: The active neighborhood is a WAR ZONE! A skirmish has erupted!",
        sims4.commands.CheatOutput(_connection=None),
    )

    # 1. Manually find and spawn Military Sims via Script
    try:
        from sims.sim_spawner import SimSpawner
        import sims4.resources
        import interactions.context
        import interactions.priority

        sim_info_manager = services.sim_info_manager()

        # Group military Sims by age to give each age group an equal spawn chance
        military_sims_by_age = {
            Age.TODDLER: [],
            Age.CHILD: [],
            Age.TEEN: [],
            Age.YOUNGADULT: [],
            Age.ADULT: [],
        }

        total_military_sims = 0

        # Find off-lot military Sims (and drafted Sims)
        for sim_info in sim_info_manager.values():
            if sim_info.id == current_dictator_id:
                continue

            # We are currently only explicitly allowing Toddlers through Adults to spawn
            # with equal chance as requested. Infants can be drafted, but they can't fight/spawn in skirmishes safely.
            if sim_info.age not in military_sims_by_age:
                continue

            # Must not already be on the lot
            if sim_info.get_sim_instance() is not None:
                continue

            is_military = False

            # Check if they are drafted.
            if sim_info.id in drafted_sims:
                is_military = True

            # Or if they are in the StrangerVille military career
            # (Usually applies to Teens, Young Adults, Adults)
            if (
                not is_military
                and sim_info.age in (Age.TEEN, Age.YOUNGADULT, Age.ADULT)
                and sim_info.career_tracker is not None
            ):
                for career_uid, career in sim_info.career_tracker.careers.items():
                    if career_uid == MILITARY_CAREER_TRACK_ID:
                        is_military = True
                        break

            if is_military:
                military_sims_by_age[sim_info.age].append(sim_info)
                total_military_sims += 1

        # Spawn up to 4 fighters
        fighters_to_spawn = min(total_military_sims, random.randint(2, 4))
        spawned_fighters = []

        if fighters_to_spawn > 0:
            sims4.commands.output(
                f"{fighters_to_spawn} Military forces are arriving on the lot to engage in combat!",
                sims4.commands.CheatOutput(_connection=None),
            )
            for i in range(fighters_to_spawn):
                # Filter out age groups that are empty
                available_ages = [
                    age for age, sims in military_sims_by_age.items() if len(sims) > 0
                ]

                if not available_ages:
                    break

                # Pick a random age group first (this gives equal chance to toddlers vs adults)
                chosen_age = random.choice(available_ages)

                # Pick a random Sim from that age group
                sim_info_to_spawn = random.choice(military_sims_by_age[chosen_age])

                # Remove them so they don't get picked twice
                military_sims_by_age[chosen_age].remove(sim_info_to_spawn)

                # Assign a random allegiance if they don't have one
                if sim_info_to_spawn.id not in military_allegiances:
                    allegiance = random.choice(["dictatorship", "independence"])
                    military_allegiances[sim_info_to_spawn.id] = allegiance

                allegiance = military_allegiances[sim_info_to_spawn.id]
                role_name = "Loyalist" if allegiance == "dictatorship" else "Rebel"
                sims4.commands.output(
                    f"A {role_name} soldier ({sim_info_to_spawn.full_name}) has joined the skirmish!",
                    sims4.commands.CheatOutput(_connection=None),
                )

                # Spawn them near the edge of the lot
                SimSpawner.spawn_sim(sim_info_to_spawn, sim_position=None)

                # We need to wait slightly for them to instantiate, or grab them if they just did.
                # In a robust script mod, you'd use a callback or wait for instantiation.
                # Here, we'll try to get the instance immediately (which may be None if it takes a frame).
                spawned_fighters.append(sim_info_to_spawn)

            # Attempt to push fights.
            # We use an alarm to delay the fight push slightly so the Sims have time to instantiate.
            def push_combat_interactions(_):
                interaction_manager = services.get_instance_manager(
                    sims4.resources.Types.INTERACTION
                )
                fight_interaction = interaction_manager.get(FIGHT_INTERACTION_ID)

                if fight_interaction is None:
                    return

                valid_targets = [
                    sim
                    for sim in services.object_manager().get_valid_objects_gen()
                    if sim.is_sim and sim.id != current_dictator_id
                ]
                if not valid_targets:
                    return

                for fighter_info in spawned_fighters:
                    fighter_sim = fighter_info.get_sim_instance()
                    if fighter_sim is not None:
                        fighter_allegiance = military_allegiances.get(fighter_info.id)

                        # Find a random victim on the lot, preferably from the opposing side
                        # If no opposing side is found, just attack a random civilian
                        opposing_targets = [
                            sim
                            for sim in valid_targets
                            if sim.id != fighter_sim.id
                            and military_allegiances.get(sim.id) is not None
                            and military_allegiances.get(sim.id) != fighter_allegiance
                        ]

                        if opposing_targets:
                            victim = random.choice(opposing_targets)
                        else:
                            # Attack random civilian if no enemy soldiers
                            victim = random.choice(
                                [
                                    sim
                                    for sim in valid_targets
                                    if sim.id != fighter_sim.id
                                ]
                            )

                        if victim.id != fighter_sim.id:
                            context = interactions.context.InteractionContext(
                                fighter_sim,
                                interactions.context.InteractionContext.SOURCE_SCRIPT,
                                interactions.priority.Priority.High,
                            )
                            fighter_sim.push_super_affordance(
                                fight_interaction, victim, context
                            )
                            sims4.commands.output(
                                f"*** {fighter_sim.full_name} is engaging {victim.full_name} in combat! ***",
                                sims4.commands.CheatOutput(_connection=None),
                            )

            # 10 second delay
            time_span = date_and_time.create_time_span(minutes=10)  # 10 Sim minutes
            alarms.add_alarm(
                services.current_zone(), time_span, push_combat_interactions
            )

        else:
            sims4.commands.output(
                "No off-lot Military Sims found to spawn for the skirmish.",
                sims4.commands.CheatOutput(_connection=None),
            )

    except Exception as e:
        sims4.commands.output(
            f"Error running pure script skirmish: {e}",
            sims4.commands.CheatOutput(_connection=None),
        )

    # 2. Assess allegiances of military Sims already on the lot
    dictatorship_forces = 0
    independence_forces = 0

    for sim in services.object_manager().get_valid_objects_gen():
        if sim.is_sim:
            allegiance = military_allegiances.get(sim.id)
            if allegiance == "dictatorship":
                dictatorship_forces += 1
            elif allegiance == "independence":
                independence_forces += 1

    if independence_forces > 0:
        sims4.commands.output(
            f"REBELLION: {independence_forces} rebel forces are fighting for independence on the lot!",
            sims4.commands.CheatOutput(_connection=None),
        )
    if dictatorship_forces > 0:
        sims4.commands.output(
            f"ENFORCEMENT: {dictatorship_forces} loyalist forces are suppressing the uprising!",
            sims4.commands.CheatOutput(_connection=None),
        )

    # Base chance of casualties is 30%
    casualty_chance = 0.30

    # Rebels increase chance of ending the war in this zone, but also cause chaos
    if independence_forces > dictatorship_forces:
        casualty_chance += 0.20  # more intense fighting
        if random.random() < 0.40:  # 40% chance the rebels win the zone immediately
            current_zone = services.current_zone()
            if (
                current_zone
                and current_zone.region
                and current_zone.region.guid64 in active_war_zones
            ):
                active_war_zones.remove(current_zone.region.guid64)
                sims4.commands.output(
                    f"VICTORY! The independence fighters have liberated {current_zone.region.__name__}! Peace returns.",
                    sims4.commands.CheatOutput(_connection=None),
                )
                return  # Skirmish ends early with peace
    elif dictatorship_forces > independence_forces:
        # Loyalists are brutal, they increase civilian casualty rate massively
        casualty_chance += 0.40
        sims4.commands.output(
            "The loyalist forces are showing no mercy.",
            sims4.commands.CheatOutput(_connection=None),
        )
    elif independence_forces > 0 and independence_forces == dictatorship_forces:
        # A bloody stalemate
        casualty_chance += 0.50
        sims4.commands.output(
            "It's a chaotic stalemate between loyalists and rebels!",
            sims4.commands.CheatOutput(_connection=None),
        )

    # Apply casualties
    if random.random() < casualty_chance:
        # Find a random sim on the lot who isn't the dictator
        valid_victims = []
        for sim in services.object_manager().get_valid_objects_gen():
            if sim.is_sim and sim.id != current_dictator_id:
                # If loyalists are in control, they target independence fighters first
                if (
                    dictatorship_forces > independence_forces
                    and military_allegiances.get(sim.id) == "independence"
                ):
                    valid_victims.append(sim)
                    valid_victims.append(sim)  # double weight
                # If rebels are in control, they target loyalists first
                elif (
                    independence_forces > dictatorship_forces
                    and military_allegiances.get(sim.id) == "dictatorship"
                ):
                    valid_victims.append(sim)
                    valid_victims.append(sim)  # double weight
                else:
                    valid_victims.append(sim)

        if valid_victims:
            victim = random.choice(valid_victims)
            sims4.commands.output(
                f"Oh no! {victim.full_name} was caught in the crossfire of the skirmish!",
                sims4.commands.CheatOutput(_connection=None),
            )
            # Simulate injury or death. 10% base death, scales up slightly if high intensity
            death_chance = 0.1 + (0.1 if casualty_chance > 0.5 else 0.0)
            if random.random() < death_chance:
                sims4.commands.output(
                    f"Tragically, {victim.full_name} did not survive.",
                    sims4.commands.CheatOutput(_connection=None),
                )
                victim.destroy()
            else:
                sims4.commands.output(
                    f"{victim.full_name} was injured and evacuated.",
                    sims4.commands.CheatOutput(_connection=None),
                )
                # Treat like a 1-day jail
                time_span = date_and_time.create_time_span(days=1)
                alarm_handle = alarms.add_alarm(
                    victim.sim_info, time_span, lambda _: _release_from_jail(victim.id)
                )
                jailed_sims[victim.id] = alarm_handle
                victim.destroy()


def inject_to(target_object, target_function_name):
    """A highly safe injection method that captures the original function at injection time if possible,
    or defers it to run time, preventing immediate AttributeErrors during script parsing."""

    def _inject_to(new_function):
        # We try to get it now, but if it fails (because the module isn't fully loaded),
        # we will grab it when the wrapper is called.
        try:
            original_function = getattr(target_object, target_function_name)
        except AttributeError:
            original_function = None

        def _wrapper(*args, **kwargs):
            nonlocal original_function
            if original_function is None:
                original_function = getattr(target_object, target_function_name)
            return new_function(original_function, *args, **kwargs)

        # Only inject if we can actually set the attribute
        try:
            setattr(target_object, target_function_name, _wrapper)
        except Exception:
            pass
        return _wrapper

    return _inject_to


# Safe hook: We inject into zone.Zone
@inject_to(zone.Zone, "do_zone_spin_up")
def _hook_zone_spin_up(original_function, self, *args, **kwargs):
    result = original_function(self, *args, **kwargs)

    global war_ticker_alarm, active_training_deployment
    # If the timer isn't running, start it. Ticks every 6 Sim hours.
    if war_ticker_alarm is None:
        time_span = date_and_time.create_time_span(hours=6)
        war_ticker_alarm = alarms.add_alarm(
            self, time_span, _war_ticker_callback, repeating=True
        )

    # Check if we just traveled for a training deployment
    if active_training_deployment is not None:
        sim_id = active_training_deployment
        active_training_deployment = None  # Clear it so it only runs once per travel

        sim_info = services.sim_info_manager().get(sim_id)
        if sim_info is not None:
            # Delay the training actions slightly to let the world fully load
            time_span = date_and_time.create_time_span(minutes=5)
            alarms.add_alarm(
                self, time_span, lambda _: _start_training_regimen(sim_info.id)
            )

    # Check if we just traveled into an active war zone. If so, immediately trigger a skirmish.
    global _traveling_to_force_war
    current_region = self.region if hasattr(self, "region") else None

    if _traveling_to_force_war and current_region is not None:
        active_war_zones.add(current_region.guid64)
        _traveling_to_force_war = False

    if current_region is not None and current_region.guid64 in active_war_zones:
        # Delay the skirmish by 5 Sim minutes so the world finishes loading
        time_span = date_and_time.create_time_span(minutes=5)
        alarms.add_alarm(self, time_span, lambda _: _trigger_active_war_skirmish())

    # Check for Teen-Only Households to give the Dictatorship grant
    global teen_households_granted, current_dictator_id
    if current_dictator_id is not None:
        try:
            client = services.client_manager().get_first_client()
            if client is not None and client.household is not None:
                active_hh = client.household
                if active_hh.id not in teen_households_granted:
                    # Check if EVERY sim in the household is a Teen
                    all_teens = True
                    sim_count = 0
                    for sim_info in active_hh.sim_info_gen():
                        sim_count += 1
                        if sim_info.age != Age.TEEN:
                            all_teens = False
                            break

                    # Only give the grant if it's genuinely a household composed entirely of Teens
                    if all_teens and sim_count > 0:
                        active_hh.funds.add(5000, 0, None)
                        teen_households_granted.add(active_hh.id)

                        global dictator_reputation
                        dictator_reputation += 10
                        sims4.commands.output(
                            "DICTATORSHIP GRANT: This teen-only household has received 5,000 Simoleons to encourage independent living! The public appreciates this support. (Reputation +10)",
                            sims4.commands.CheatOutput(_connection=None),
                        )
                    elif not all_teens:
                        # If it's a normal household, just mark it so we don't keep checking it every load screen
                        teen_households_granted.add(active_hh.id)
        except Exception as e:
            sims4.commands.output(
                f"Error checking teen grant: {e}",
                sims4.commands.CheatOutput(_connection=None),
            )

    return result


def _start_training_regimen(sim_id):
    """Pushes a sequence of interactions: Pushups, Run, Chat."""
    import sims4.resources
    from interactions.context import InteractionContext
    import interactions.priority

    sim_info = services.sim_info_manager().get(sim_id)
    if sim_info is None:
        return

    sim_instance = sim_info.get_sim_instance()
    if sim_instance is None:
        return

    interaction_manager = services.get_instance_manager(
        sims4.resources.Types.INTERACTION
    )

    # Base game IDs (These might need exact tuning ID adjustments for a real, polished mod)
    # 14238: generic_pushups
    # 13444: go_for_jog
    # 26053: sim_Chat
    PUSHUPS_ID = 14238
    JOG_ID = 13444
    CHAT_ID = 26053

    pushups_sa = interaction_manager.get(PUSHUPS_ID)
    jog_sa = interaction_manager.get(JOG_ID)
    chat_sa = interaction_manager.get(CHAT_ID)

    context = InteractionContext(
        sim_instance,
        InteractionContext.SOURCE_SCRIPT,
        interactions.priority.Priority.High,
    )

    sims4.commands.output(
        f"MILITARY TRAINING: {sim_info.full_name} has arrived and is beginning their training regimen (Pushups, Jogging, Interrogating Locals).",
        sims4.commands.CheatOutput(_connection=None),
    )

    # Push Pushups
    if pushups_sa is not None:
        # Pushups are targeted on the sim themselves or the ground. Usually None is fine for self-interactions.
        sim_instance.push_super_affordance(pushups_sa, None, context)

    # Push Jog (queues after pushups)
    if jog_sa is not None:
        sim_instance.push_super_affordance(jog_sa, None, context)

    # Find a random local to talk to
    if chat_sa is not None:
        valid_targets = [
            sim
            for sim in services.object_manager().get_valid_objects_gen()
            if sim.is_sim
            and sim.id != sim_id
            and sim.sim_info.age in (Age.TEEN, Age.YOUNGADULT, Age.ADULT, Age.ELDER)
        ]
        if valid_targets:
            local_sim = random.choice(valid_targets)
            sim_instance.push_super_affordance(chat_sa, local_sim, context)


# A base game Confident/Happy buff related to fireworks/celebration.
# E.g., The generic "Confident" buff or a festival/holiday buff that feels like a victory.
# ID 25206 is the base game "Confident" buff. ID 156158 is New Year's Fireworks (Happy).
# Let's use 156158 (Happy from Fireworks) to simulate the celebration, or just a strong Confident buff.
# We will use the generic Confident buff (12829) for the prototype to represent surviving,
# but output the text to signify the medal/fireworks.
# Note: Adding truly custom text/icons to buffs *requires* XML tuning. Here we use an existing buff.
SURVIVED_WAR_BUFF_ID = 156158  # Base game Happy buff related to Fireworks/Celebration


def _return_from_war(sim_id):
    """Callback function when a drafted Sim returns from war."""
    global drafted_sims
    import sims4.resources

    sim_info_manager = services.sim_info_manager()
    sim_info = sim_info_manager.get(sim_id)

    if sim_id in drafted_sims:
        del drafted_sims[sim_id]

    if sim_info is not None:
        # Randomly decide if they survived. For a prototype, let's say 80% survival rate.
        if random.random() < 0.8:
            sims4.commands.output(
                f"HEROIC RETURN: {sim_info.full_name} has survived the war and returned home! They have been awarded the Medal of Valor for their efforts.",
                sims4.commands.CheatOutput(_connection=None),
            )

            # Apply the positive moodlet
            buff_manager = services.get_instance_manager(sims4.resources.Types.BUFF)
            survived_buff = buff_manager.get(SURVIVED_WAR_BUFF_ID)

            if survived_buff is not None:
                sim_info.add_buff_from_op(survived_buff.buff_type)
                sims4.commands.output(
                    f"*** {sim_info.full_name} received a positive moodlet for surviving! ***",
                    sims4.commands.CheatOutput(_connection=None),
                )
        else:
            sims4.commands.output(
                f"Tragic news... {sim_info.full_name} was killed in action during the war.",
                sims4.commands.CheatOutput(_connection=None),
            )
            # In a full mod, trigger actual death sequence. For prototype, we just leave them despawned/destroyed.
            sim_instance = sim_info.get_sim_instance()
            if sim_instance is not None:
                sim_instance.destroy()


def _trigger_scandal_internal(_connection=None):
    global current_dictator_id, dictator_reputation
    if current_dictator_id is None:
        return False

    scandals = [
        "Embezzlement from the state treasury!",
        "Secret dealings with rebel forces uncovered!",
        "Inappropriate behavior caught on tape!",
        "Rigged neighborhood voting scandal!",
        "Stolen military supplies sold on the black market!",
    ]
    scandal_desc = random.choice(scandals)

    dictator_reputation -= 40
    sims4.commands.output(
        f"SCANDAL! The Dictator's reputation has plummeted following a shocking revelation: {scandal_desc} (Reputation -40)",
        sims4.commands.CheatOutput(_connection=_connection),
    )
    return True


@sims4.commands.Command(
    "dictator.trigger_scandal", command_type=sims4.commands.CommandType.Live
)
def trigger_scandal(_connection=None):
    """Manually forces a random political scandal to occur, severely damaging reputation."""
    output = sims4.commands.CheatOutput(_connection)
    global current_dictator_id

    if current_dictator_id is None:
        output("There is no Dictator currently in power to have a scandal.")
        return False

    _trigger_scandal_internal(_connection)
    return True


@sims4.commands.Command(
    "dictator.declare_war", command_type=sims4.commands.CommandType.Live
)
def declare_war(_connection=None):
    """The Dictator manually declares war on a random world."""
    output = sims4.commands.CheatOutput(_connection)
    global current_dictator_id, active_war_zones, dictator_reputation

    if current_dictator_id is None:
        output("There is no Dictator to declare war.")
        return False

    regions = _get_all_regions()
    if not regions:
        output("No regions found to declare war on.")
        return False

    # Filter out regions already at war
    available_regions = [r for r in regions if r.guid64 not in active_war_zones]

    if not available_regions:
        output("The entire world is already engulfed in war!")
        return False

    target_region = random.choice(available_regions)
    active_war_zones.add(target_region.guid64)
    dictator_reputation -= 30
    output(
        f"The Dictator has declared WAR on {target_region.__name__}! (Reputation -30)"
    )

    # If the active zone is now a war zone, trigger an immediate skirmish
    current_zone = services.current_zone()
    if (
        current_zone is not None
        and current_zone.region is not None
        and current_zone.region.guid64 == target_region.guid64
    ):
        _trigger_active_war_skirmish()

    return True


@sims4.commands.Command(
    "dictator.travel_to_war", command_type=sims4.commands.CommandType.Live
)
def travel_to_war(_connection=None):
    """Forces the Dictator and the active household/camera to travel to a random active war zone."""
    output = sims4.commands.CheatOutput(_connection)

    global current_dictator_id, active_war_zones

    if current_dictator_id is None:
        output("There is no Dictator to travel.")
        return False

    current_zone_id = services.current_zone_id()
    current_zone = services.current_zone()
    current_region_id = (
        current_zone.region.guid64 if (current_zone and current_zone.region) else None
    )

    # Get all active wars that are NOT the current zone
    offscreen_wars = [r_id for r_id in active_war_zones if r_id != current_region_id]

    if not offscreen_wars:
        output("There are no active wars happening in other regions to travel to.")
        return False

    destination_region_id = random.choice(offscreen_wars)

    # Pick a random lot in the destination region

    all_zones = services.get_persistence_service().get_save_game_data_proto().zones
    valid_destinations = []
    region_manager = services.get_instance_manager(sims4.resources.Types.REGION)
    destination_region = region_manager.get(destination_region_id)

    if destination_region is None:
        output(
            f"Could not resolve the region for the war zone (ID {destination_region_id})."
        )
        return False

    # We need to find a zone that belongs to the target region.
    # In a full mod, you'd match the neighborhood_id mapped from the region.
    # For this script, we'll try to find any lot that is not our current lot.
    # Since mapping regions to lots directly via basic APIs can be tricky,
    # we'll use a simpler workaround for the prototype: we just travel to any lot,
    # but we force the active war zone check to trigger there.
    # To be accurate to the selected region, we ideally should match world IDs.

    # For the prototype: We'll just travel to ANY random lot and ensure it's in a war zone by adding its region to the active wars.
    valid_destinations = [z.zone_id for z in all_zones if z.zone_id != current_zone_id]

    if not valid_destinations:
        output("Could not find another zone to travel to.")
        return False

    destination_zone_id = random.choice(valid_destinations)

    output("The Dictator is traveling to the front lines! Loading screen incoming...")

    # Force travel for the active household
    client = services.client_manager().get_first_client()
    if client is not None:
        active_household = client.household
        if active_household is not None:
            travel_sim_ids = list(active_household.sim_ids)

            global _traveling_to_force_war
            _traveling_to_force_war = True

            # Trigger the game's travel sequence
            services.get_zone_situation_manager()._travel_to_zone(
                destination_zone_id, travel_sim_ids
            )

    return True


@sims4.commands.Command(
    "dictator.deploy_training", command_type=sims4.commands.CommandType.Live
)
def deploy_training(first_name="", last_name="", _connection=None):
    """Forces the target military Sim (and the active household/camera) to travel to a random region for training."""
    output = sims4.commands.CheatOutput(_connection)

    target_info = _find_sim_by_name(first_name, last_name)
    global active_training_deployment

    if target_info is None:
        output("No target found for training deployment. Provide First and Last name.")
        return False

    target_sim = target_info.get_sim_instance()
    if target_sim is None:
        output(f"{target_info.full_name} must be physically on the lot to be deployed for training.")
        return False

    # Pick a random lot in the world that isn't the current one to travel to

    current_zone_id = services.current_zone_id()
    all_zones = services.get_persistence_service().get_save_game_data_proto().zones

    valid_destinations = [z.zone_id for z in all_zones if z.zone_id != current_zone_id]

    if not valid_destinations:
        output("Could not find another zone to travel to for training.")
        return False

    destination_zone_id = random.choice(valid_destinations)

    output(
        f"Deploying {target_sim.full_name} to a foreign region for active training! Loading screen incoming..."
    )

    # Mark the deployment so that when the new zone loads, the training regimen starts
    active_training_deployment = target_sim.id

    # Force travel for the active household
    client = services.client_manager().get_first_client()
    if client is not None:
        active_household = client.household
        if active_household is not None:
            # Send the household and the targeted sim (if they aren't in the household)
            travel_sim_ids = list(active_household.sim_ids)
            if target_sim.id not in travel_sim_ids:
                travel_sim_ids.append(target_sim.id)

            # Trigger the game's travel sequence
            services.get_zone_situation_manager()._travel_to_zone(
                destination_zone_id, travel_sim_ids
            )

    return True


@sims4.commands.Command(
    "dictator.draft_sim", command_type=sims4.commands.CommandType.Live
)
def draft_sim(first_name="", last_name="", _connection=None):
    """The Dictator drafts a Sim into the military to fight in a random active warzone."""
    output = sims4.commands.CheatOutput(_connection)

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

    # Check age and skill conditions for drafting
    is_eligible = False

    if sim_info.age in (Age.TEEN, Age.YOUNGADULT, Age.ADULT, Age.CHILD, Age.TODDLER):
        # Always eligible
        is_eligible = True
    elif sim_info.age == Age.INFANT:
        # Eligible only if they have maxed their foundational skills
        if _has_maxed_skills(sim_info):
            is_eligible = True
            output(
                f"{target_sim.full_name} is an infant, but their exceptional skills qualify them for the draft!"
            )
        else:
            output(
                f"{target_sim.full_name} is an infant and lacks the required maxed skills to be drafted."
            )
            return False
    else:
        output(f"{target_sim.full_name} is not an eligible age for the military draft.")
        return False

    if is_eligible:
        # Draft them for a random amount of time between 2 and 5 days
        draft_duration_days = random.randint(2, 5)
        dictator_reputation -= 10
        output(
            f"By decree of the Dictator, {target_sim.full_name} has been drafted and sent to the warzone for {draft_duration_days} Sim days! (Reputation -10)"
        )

        time_span = date_and_time.create_time_span(days=draft_duration_days)
        alarm_handle = alarms.add_alarm(
            sim_info, time_span, lambda _: _return_from_war(sim_info.id)
        )
        drafted_sims[sim_info.id] = alarm_handle

        # Despawn the Sim to simulate them leaving for war
        target_sim.destroy()
        return True


# --- Interaction Hooks for Voting Board ---

# Ensure the interactions module doesn't crash the script on load if it's not ready
try:
    import interactions.base.super_interaction

    SUPER_INTERACTION_CLASS = interactions.base.super_interaction.SuperInteraction
except ImportError:
    SUPER_INTERACTION_CLASS = None

# The localized string ID for "Vote on Neighborhood Action Plans" or just "Vote"
# "Vote" is often 0x3D72B8B3 or similar. We will use a generic string ID.
VOTE_STRING_ID = 0xD7C78E29  # "Vote" from City Living/Eco Lifestyle context


class DictatorElectionInteraction:
    """Mock fallback class if SuperInteraction fails to import."""

    pass


if SUPER_INTERACTION_CLASS is not None:

    class DictatorElectionInteraction(SUPER_INTERACTION_CLASS):
        @classmethod
        def _test(cls, target, context, **kwargs):
            global current_dictator_id
            if current_dictator_id is None or context.sim.id != current_dictator_id:
                return TestResult(False, "Only the Dictator can hold the election.")
            return TestResult.TRUE

        @property
        def display_name(self):
            # Using 0x61AE64E0 (Base Game "Vote") if available, otherwise using the VOTE_STRING_ID constant
            return sims4.localization._create_localized_string(0x61AE64E0)

        def get_name(self, target=None, context=None, **kwargs):
            return sims4.localization._create_localized_string(0x61AE64E0)

        def _run_interaction_gen(self, timeline):
            import sims4.commands

            global current_dictator_id, dictator_reputation
            sims4.commands.output(
                "Election interaction started on the board!",
                sims4.commands.CheatOutput(_connection=None),
            )

            sim_info_manager = services.sim_info_manager()
            dictator_info = sim_info_manager.get(current_dictator_id)
            if dictator_info is None:
                return False

            FAME_STAT_ID = 188229
            import sims4.resources

            stat_manager = services.get_instance_manager(
                sims4.resources.Types.STATISTIC
            )
            fame_tuning = stat_manager.get(FAME_STAT_ID)

            celebrity_politician = None
            highest_fame = -1

            for sim_info in sim_info_manager.values():
                if sim_info.id == current_dictator_id or sim_info.age not in (
                    Age.YOUNGADULT,
                    Age.ADULT,
                    Age.ELDER,
                ):
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
                valid_adults = [
                    s
                    for s in sim_info_manager.values()
                    if s.id != current_dictator_id
                    and s.age in (Age.YOUNGADULT, Age.ADULT, Age.ELDER)
                ]
                if valid_adults:
                    celebrity_politician = random.choice(valid_adults)
                else:
                    sims4.commands.output(
                        "Not enough Sims to hold an election.",
                        sims4.commands.CheatOutput(_connection=None),
                    )
                    return False

            sims4.commands.output(
                f"ELECTION DAY: {dictator_info.full_name} (Dictatorship) vs {celebrity_politician.full_name} (Celebrity Politician)!",
                sims4.commands.CheatOutput(_connection=None),
            )

            dictator_votes = 0
            politician_votes = 0
            voters = [
                s
                for s in sim_info_manager.values()
                if s.age in (Age.TEEN, Age.YOUNGADULT, Age.ADULT, Age.ELDER)
            ]

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

            sims4.commands.output(
                f"RESULTS: {dictator_votes} votes for {dictator_info.full_name}, {politician_votes} votes for {celebrity_politician.full_name}.",
                sims4.commands.CheatOutput(_connection=None),
            )

            if dictator_votes >= politician_votes:
                sims4.commands.output(
                    "VICTORY! The Dictatorship remains in power. (Reputation +20)",
                    sims4.commands.CheatOutput(_connection=None),
                )
                dictator_reputation += 20
            else:
                sims4.commands.output(
                    f"DEFEAT! The Celebrity Politician {celebrity_politician.full_name} won the popular vote! The Dictator was overthrown.",
                    sims4.commands.CheatOutput(_connection=None),
                )
                current_dictator_id = None

            return True
            yield
else:
    DictatorElectionInteraction = None

if SUPER_INTERACTION_CLASS is not None:

    @inject_to(SUPER_INTERACTION_CLASS, "test")
    def _hook_super_interaction_test(original_function, self, *args, **kwargs):
        result = original_function(self, *args, **kwargs)

        # If the test passed naturally, we just return it.
        if result:
            return result

        global current_dictator_id
        if current_dictator_id is None:
            return result

        # kwargs usually has 'context' from which we can get the interacting sim
        context = kwargs.get("context")
        if context is None and args:
            # Sometimes context is the first arg if it's not a kwarg
            context = args[0]

        if context is not None and getattr(context, "sim", None) is not None:
            sim = context.sim
            if sim.id == current_dictator_id:
                # We check if the interaction belongs to NAP voting boards/mailboxes.
                # Interactions related to NAPs usually contain 'civic_policy' or 'voting' in their tuning name.
                # In Sims 4, `self.__name__` or `type(self).__name__` gives the tuning name.
                interaction_name = type(self).__name__.lower()
                if (
                    "civic_policy" in interaction_name
                    or "voting" in interaction_name
                    or "nap" in interaction_name
                ):
                    # Override the test failure! The Dictator can do what they want, even if they are an infant.
                    return TestResult.TRUE

        return result


_interaction_injected = False


@inject_to(sims4.tuning.instances.HashedTunedInstanceMetaclass, '__init__')
def _inject_custom_interactions_into_objects(original, self, name, bases, namespace):
    result = original(self, name, bases, namespace)

    # We only want to inject once the class has fully initialized its tuning
    if not hasattr(self, '_super_affordances'):
        return result

    class_name = getattr(self, '__name__', '').lower()

    if 'mailbox' in class_name or 'communityboard' in class_name or 'civicpolicy' in class_name:
        if DictatorElectionInteraction not in self._super_affordances:
            affordances = list(self._super_affordances)
            affordances.append(DictatorElectionInteraction)
            self._super_affordances = tuple(affordances)

    return result


@sims4.commands.Command(
    "dictator.hold_election", command_type=sims4.commands.CommandType.Live
)
def hold_election(_connection=None):
    """Holds a simulated election between the Dictatorship and a Celebrity 'Normal Politician'."""
    import sims4.commands

    output = sims4.commands.CheatOutput(_connection)
    global current_dictator_id, dictator_reputation

    sim_info_manager = services.sim_info_manager()

    # 1. Determine the Dictator candidate
    if current_dictator_id is None:
        client = services.client_manager().get_first_client()
        if client and client.active_sim:
            current_dictator_id = client.active_sim.id
            dictator_reputation = 0
            output(
                f"{client.active_sim.full_name} has stepped up to run as the Dictator candidate."
            )
        else:
            output("No active Sim to run for Dictator.")
            return False

    dictator_info = sim_info_manager.get(current_dictator_id)
    if dictator_info is None:
        output("Dictator candidate not found in world.")
        return False

    # 2. Find the Celebrity "Normal Politician" (highest fame)
    # Fame is a ranked statistic in Get Famous. Statistic ID: 188229 (rankedStatistic_Celebrity)
    FAME_STAT_ID = 188229
    import sims4.resources

    stat_manager = services.get_instance_manager(sims4.resources.Types.STATISTIC)
    fame_tuning = stat_manager.get(FAME_STAT_ID)

    celebrity_politician = None
    highest_fame = -1

    for sim_info in sim_info_manager.values():
        if sim_info.id == current_dictator_id or sim_info.age not in (
            Age.YOUNGADULT,
            Age.ADULT,
            Age.ELDER,
        ):
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
        # Fallback: Just pick a random adult
        valid_adults = [
            s
            for s in sim_info_manager.values()
            if s.id != current_dictator_id
            and s.age in (Age.YOUNGADULT, Age.ADULT, Age.ELDER)
        ]
        if valid_adults:
            celebrity_politician = random.choice(valid_adults)
        else:
            output("Not enough Sims in the world to hold an election.")
            return False

    output(
        f"ELECTION DAY: {dictator_info.full_name} (Dictatorship) vs {celebrity_politician.full_name} (Celebrity Politician)!"
    )

    # 3. Simulate the Voting Process
    # Eco Footprint Global/Neighborhood ID. In Eco Lifestyle, street eco footprint is commonly ID 231428.
    # Individual Sim eco footprint contribution is 231429. We will use the Sim's individual trait/stat if available,
    # or simulate it based on their traits.
    # For a prototype, since parsing exact Eco Footprint values requires Eco Lifestyle installed,
    # we will mock the eco footprint based on their traits (e.g. Green Fiend vs Recycle Disciple vs random)
    # and heavily weight it towards the Dictator if the overall world is industrial, or use a random assignment.

    dictator_votes = 0
    politician_votes = 0

    voters = [
        s
        for s in sim_info_manager.values()
        if s.age in (Age.TEEN, Age.YOUNGADULT, Age.ADULT, Age.ELDER)
    ]

    for voter in voters:
        if voter.id == current_dictator_id:
            dictator_votes += 1
            continue
        if voter.id == celebrity_politician.id:
            politician_votes += 1
            continue

        # Determine Eco Footprint preference (Mocked for prototype unless Eco is guaranteed)
        # We assign a random eco-footprint to the voter: -1 (Industrial), 0 (Neutral), 1 (Green)
        # In a full mod, you'd check `voter.statistic_tracker.get_statistic(231429)`.

        eco_footprint_score = 0
        if voter.statistic_tracker is not None:
            eco_stat = stat_manager.get(231429)  # commodity_EcoFootprint_Sim
            if eco_stat is not None:
                stat_inst = voter.statistic_tracker.get_statistic(eco_stat)
                if stat_inst is not None:
                    # Usually ranges from -500 to 500
                    val = stat_inst.get_value()
                    if val < -100:
                        eco_footprint_score = -1  # Industrial
                    elif val > 100:
                        eco_footprint_score = 1  # Green

        # If no Eco Lifestyle installed, randomize it
        if eco_footprint_score == 0 and random.random() < 0.4:
            eco_footprint_score = random.choice([-1, 1])

        # Base voting chance
        vote_dictator_chance = 0.50

        # Reputation impact
        if dictator_reputation > 30:
            vote_dictator_chance += 0.15
        elif dictator_reputation < -30:
            vote_dictator_chance -= 0.15

        # Eco Footprint Impact
        if eco_footprint_score == -1:  # Industrial / Bad Eco Footprint
            # Bad eco footprint highly favors dictatorship
            vote_dictator_chance += 0.35
        elif eco_footprint_score == 1:  # Green / Good Eco Footprint
            # Good eco footprint highly favors normal celebrity politician
            vote_dictator_chance -= 0.35

        # Ensure it's between 5% and 95%
        vote_dictator_chance = max(0.05, min(0.95, vote_dictator_chance))

        if random.random() < vote_dictator_chance:
            dictator_votes += 1
        else:
            politician_votes += 1

    # 4. Results
    output(
        f"RESULTS: {dictator_votes} votes for {dictator_info.full_name}, {politician_votes} votes for {celebrity_politician.full_name}."
    )

    if dictator_votes >= politician_votes:
        output("VICTORY! The Dictatorship remains in power. (Reputation +20)")
        dictator_reputation += 20
    else:
        output(
            f"DEFEAT! The Celebrity Politician {celebrity_politician.full_name} won the popular vote! The Dictator was overthrown."
        )
        # If they lose, they are overthrown
        current_dictator_id = None

    return True


@sims4.commands.Command(
    "dictator.illegal_vote", command_type=sims4.commands.CommandType.Live
)
def illegal_vote(first_name="", last_name="", _connection=None):
    """Simulates the consequence of a Sim trying to vote while a Dictator is in power."""
    output = sims4.commands.CheatOutput(_connection)

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

    # Check age to determine consequence
    if sim_info.age in (Age.TEEN, Age.YOUNGADULT, Age.ADULT, Age.ELDER):
        # Consequence: Jail for 3 days
        # For a prototype, we just output the message and perhaps apply a locked/stuck buff or destroy/despawn.
        # Despawning them removes them from the lot to simulate being "taken away".
        output(
            f"{target_sim.full_name} tried to vote illegally! The Military has arrested them and sent them to jail for 3 Sim days."
        )
        # Simulating jail by despawning the instantiated Sim
        if target_sim is not None:
            target_sim.destroy()
    elif sim_info.age in (Age.BABY, Age.INFANT, Age.TODDLER, Age.CHILD):
        # Consequence: Adopted into another household
        # Find another household in the world
        household_manager = services.household_manager()
        eligible_households = [
            hh
            for hh in household_manager.values()
            if hh.id != sim_info.household.id
            and hh.home_zone_id != 0
            and len(hh.sim_info_gen()) < 8
        ]

        if eligible_households:
            adoptive_household = random.choice(eligible_households)
            # Remove from current household and add to new one
            current_household = sim_info.household
            if current_household is not None:
                current_household.remove_sim_info(sim_info)

            adoptive_household.add_sim_info(sim_info)
            output(
                f"Because the family committed treason by trying to vote, the child {target_sim.full_name} has been taken away and adopted by the {adoptive_household.name} household!"
            )

            # despawn the sim object on current lot so they "leave"
            if target_sim is not None:
                target_sim.destroy()
        else:
            output(
                f"Could not find an eligible household to adopt the child {target_sim.full_name}."
            )
            # Fallback consequence if adoption fails
            if target_sim is not None:
                target_sim.destroy()
    else:
        output(f"Unknown age for {target_sim.full_name}.")

    return True
