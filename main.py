import sims4.commands
import services
from server_commands.argument_helpers import OptionalTargetParam, get_optional_target
from sims.sim_info_types import Age
import random
import alarms
import date_and_time
import zone
from world.region import Region

# --- Mod State ---
current_dictator_id = None
active_rules = set()
jailed_sims = {}  # {sim_id: alarm_handle}
active_training_deployment = None # {sim_id}
_traveling_to_force_war = False
teen_households_granted = set() # {household_id}

# Core Skill IDs for max check
# Note: These are base game example IDs.
# Infant: Fine Motor (280058), Gross Motor (280061), Crawling/Walking etc.
# Toddler: Communication (140170), Imagination (140706), Movement (136140), Potty (144913), Thinking (140504)
# Child: Creativity (16718), Mental (16719), Motor (16720), Social (16721)

SKILLS_INFANT = [280058, 280061] # Usually max at level 3
SKILLS_TODDLER = [140170, 140706, 136140, 144913, 140504] # Most max at 5, potty at 3
SKILLS_CHILD = [16718, 16719, 16720, 16721] # Max at 10

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
        return False # This function is only for young ages

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
drafted_sims = {} # {sim_id: alarm_handle}
active_war_zones = set() # {region_id}
military_allegiances = {} # {sim_id: "dictatorship" or "independence"}
war_ticker_alarm = None

# A simplified mock of a "fight" interaction ID. In reality, you'd find the
# correct Interaction SA (Super Interaction) ID for fighting from the game files.
FIGHT_INTERACTION_ID = 14243  # Example ID, might need tuning for a real mod.
MILITARY_CAREER_TRACK_ID = 202483  # StrangerVille military career

@sims4.commands.Command('dictator.make_dictator', command_type=sims4.commands.CommandType.Live)
def make_dictator(opt_target: OptionalTargetParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    target = get_optional_target(opt_target, _connection)

    if target is None:
        output("No target found.")
        return False

    global current_dictator_id
    current_dictator_id = target.id
    output(f"{target.full_name} is now the Dictator!")
    return True

@sims4.commands.Command('dictator.die', command_type=sims4.commands.CommandType.Live)
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
                        output(f"Succession! {heir_info.full_name} is now the new Dictator!")
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

@sims4.commands.Command('dictator.set_rule', command_type=sims4.commands.CommandType.Live)
def set_rule(rule_name: str, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    global current_dictator_id, active_rules

    if current_dictator_id is None:
        output("There is no Dictator to set rules.")
        return False

    if not rule_name:
        output("Please specify a rule name (e.g., no_dancing).")
        return False

    active_rules.add(rule_name.lower())
    output(f"The Dictator has decreed a new rule: {rule_name.upper()}!")
    return True

@sims4.commands.Command('dictator.remove_rule', command_type=sims4.commands.CommandType.Live)
def remove_rule(rule_name: str, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    global current_dictator_id, active_rules

    if current_dictator_id is None:
        output("There is no Dictator to remove rules.")
        return False

    rule_name = rule_name.lower()
    if rule_name in active_rules:
        active_rules.remove(rule_name)
        output(f"The Dictator has revoked the rule: {rule_name.upper()}!")
        return True
    else:
        output(f"Rule '{rule_name}' is not currently active.")
        return False

import sims4.resources
from interactions.context import InteractionContext
import interactions.priority

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

@sims4.commands.Command('dictator.break_rule', command_type=sims4.commands.CommandType.Live)
def break_rule(rule_name: str, opt_target: OptionalTargetParam = None, _connection=None):
    """Simulates a Sim breaking a rule and being punished via a physical fight."""
    output = sims4.commands.CheatOutput(_connection)
    target_sim = get_optional_target(opt_target, _connection)

    global current_dictator_id, active_rules

    if target_sim is None:
        output("No target found to break the rule.")
        return False

    if current_dictator_id is None:
        output("There is no Dictator, so there are no rules to break.")
        return False

    if target_sim.id == current_dictator_id:
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

    # 2. Push a fight interaction
    # Fight interaction tuning ID. In base game, generic fight is often 14243.
    # We load the tuning snippet and push it onto the enforcer's queue targeting the rulebreaker.
    try:
        interaction_manager = services.get_instance_manager(sims4.resources.Types.INTERACTION)
        fight_interaction = interaction_manager.get(FIGHT_INTERACTION_ID)

        if fight_interaction is not None:
            # Create an interaction context for the enforcer.
            context = InteractionContext(
                enforcer_sim,
                InteractionContext.SOURCE_SCRIPT,
                interactions.priority.Priority.High
            )
            # Push the interaction
            enforcer_sim.push_super_affordance(
                fight_interaction,
                target_sim,
                context
            )
            output(f"*** {enforcer_sim.full_name} initiated a fight with {target_sim.full_name}! ***")

            # Since tracking actual interaction results (who won the fight) requires complex state listeners in Python,
            # we will simulate the outcome here via a delayed alarm. If the enforcer wins (higher chance), the target is arrested.
            def _resolve_fight_arrest(_):
                # 70% chance the military enforcer wins and arrests them
                if random.random() < 0.70:
                    sims4.commands.output(f"{enforcer_sim.full_name} subdued {target_sim.full_name}! They are being sent to jail for 2 days for breaking the rule.", sims4.commands.CheatOutput(_connection=None))

                    time_span = date_and_time.create_time_span(days=2)
                    alarm_handle = alarms.add_alarm(target_sim.sim_info, time_span, lambda _: _release_from_jail(target_sim.id))
                    jailed_sims[target_sim.id] = alarm_handle
                    target_sim.destroy()
                else:
                    sims4.commands.output(f"{target_sim.full_name} managed to escape the Military after the fight! They remain free.", sims4.commands.CheatOutput(_connection=None))

            # Set alarm for 30 sim minutes to let the fight happen before resolving the arrest
            time_span = date_and_time.create_time_span(minutes=30)
            alarms.add_alarm(services.current_zone(), time_span, _resolve_fight_arrest)

        else:
            output("Error: Could not load the fight interaction data.")
    except Exception as e:
        output(f"Error pushing fight interaction: {e}")

    return True

@sims4.commands.Command('dictator.arrest', command_type=sims4.commands.CommandType.Live)
def arrest_sim(opt_target: OptionalTargetParam = None, _connection=None):
    """The Dictator instantly orders the arrest of a target Sim without a fight."""
    output = sims4.commands.CheatOutput(_connection)
    target_sim = get_optional_target(opt_target, _connection)

    global current_dictator_id, jailed_sims

    if current_dictator_id is None:
        output("There is no Dictator to issue an arrest warrant.")
        return False

    if target_sim is None:
        output("No target found to arrest.")
        return False

    if target_sim.id == current_dictator_id:
        output("The Dictator cannot be arrested!")
        return False

    output(f"By decree of the Dictator, {target_sim.full_name} has been arrested and sent to jail for 3 Sim days!")

    time_span = date_and_time.create_time_span(days=3)
    alarm_handle = alarms.add_alarm(target_sim.sim_info, time_span, lambda _: _release_from_jail(target_sim.id))
    jailed_sims[target_sim.id] = alarm_handle

    # Send them to jail (despawn)
    target_sim.destroy()
    return True

@sims4.commands.Command('dictator.banish', command_type=sims4.commands.CommandType.Live)
def banish(opt_target: OptionalTargetParam = None, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    target = get_optional_target(opt_target, _connection)

    if target is None:
        output("No target found.")
        return False

    if target.id == current_dictator_id:
        output("You cannot banish the Dictator!")
        return False

    output(f"{target.full_name} has been banished by the Dictator!")
    target.destroy()
    return True

@sims4.commands.Command('dictator.demand_taxes', command_type=sims4.commands.CommandType.Live)
def demand_taxes(amount: int = 1000, _connection=None):
    output = sims4.commands.CheatOutput(_connection)

    global current_dictator_id
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
    output(f"The Dictator has demanded and received {amount} Simoleons in taxes!")
    return True

@sims4.commands.Command('dictator.set_allegiance', command_type=sims4.commands.CommandType.Live)
def set_allegiance(allegiance: str, opt_target: OptionalTargetParam = None, _connection=None):
    """Sets the military allegiance of a Sim to 'dictatorship' or 'independence'."""
    output = sims4.commands.CheatOutput(_connection)
    target_sim = get_optional_target(opt_target, _connection)

    global military_allegiances

    if target_sim is None:
        output("No target found to set allegiance.")
        return False

    allegiance = allegiance.lower()
    if allegiance not in ["dictatorship", "independence"]:
        output("Allegiance must be either 'dictatorship' or 'independence'.")
        return False

    military_allegiances[target_sim.id] = allegiance
    output(f"{target_sim.full_name}'s allegiance has been set to: {allegiance.upper()}!")
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
        sims4.commands.output(f"{sim_info.full_name} has served their jail sentence and is released.", sims4.commands.CheatOutput(_connection=None))

def _war_ticker_callback(_):
    """Fires periodically to start or end wars, and trigger skirmishes."""
    global active_war_zones, current_dictator_id

    if current_dictator_id is None:
        # If the dictator dies/falls, wars slowly end.
        if active_war_zones and random.random() < 0.5:
            ended_region_id = active_war_zones.pop()
            sims4.commands.output(f"With the regime gone, peace returns to a former war zone.", sims4.commands.CheatOutput(_connection=None))
        return

    regions = _get_all_regions()
    if not regions:
        return

    # Chance to start a new war (10% chance every tick)
    if random.random() < 0.10:
        target_region = random.choice(regions)
        if target_region.guid64 not in active_war_zones:
            active_war_zones.add(target_region.guid64)
            sims4.commands.output(f"BREAKING NEWS: War has broken out in {target_region.__name__}!", sims4.commands.CheatOutput(_connection=None))

    # Chance to end an existing war (15% chance per tick for any given war)
    wars_to_end = []
    for region_id in list(active_war_zones):
        if random.random() < 0.15:
            wars_to_end.append(region_id)

    for region_id in wars_to_end:
        active_war_zones.remove(region_id)
        sims4.commands.output("A ceasefire has been declared in one of the active war zones.", sims4.commands.CheatOutput(_connection=None))

    # Skirmish check: Is the current active lot in a war zone?
    current_zone = services.current_zone()
    if current_zone is not None:
        current_region = current_zone.region
        if current_region is not None and current_region.guid64 in active_war_zones:
            _trigger_active_war_skirmish()

def _trigger_active_war_skirmish():
    """A skirmish happens on the active lot because it's in a war zone.
       Pure script implementation (no custom XML Situations)."""
    global current_dictator_id, military_allegiances, active_war_zones
    sims4.commands.output("WARNING: The active neighborhood is a WAR ZONE! A skirmish has erupted!", sims4.commands.CheatOutput(_connection=None))

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
            Age.ADULT: []
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
            if not is_military and sim_info.age in (Age.TEEN, Age.YOUNGADULT, Age.ADULT) and sim_info.career_tracker is not None:
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
            sims4.commands.output(f"{fighters_to_spawn} Military forces are arriving on the lot to engage in combat!", sims4.commands.CheatOutput(_connection=None))
            for i in range(fighters_to_spawn):
                # Filter out age groups that are empty
                available_ages = [age for age, sims in military_sims_by_age.items() if len(sims) > 0]

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
                sims4.commands.output(f"A {role_name} soldier ({sim_info_to_spawn.full_name}) has joined the skirmish!", sims4.commands.CheatOutput(_connection=None))

                # Spawn them near the edge of the lot
                SimSpawner.spawn_sim(sim_info_to_spawn, sim_position=None)

                # We need to wait slightly for them to instantiate, or grab them if they just did.
                # In a robust script mod, you'd use a callback or wait for instantiation.
                # Here, we'll try to get the instance immediately (which may be None if it takes a frame).
                spawned_fighters.append(sim_info_to_spawn)

            # Attempt to push fights.
            # We use an alarm to delay the fight push slightly so the Sims have time to instantiate.
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

                        # Find a random victim on the lot, preferably from the opposing side
                        # If no opposing side is found, just attack a random civilian
                        opposing_targets = [sim for sim in valid_targets if sim.id != fighter_sim.id and
                                            military_allegiances.get(sim.id) is not None and
                                            military_allegiances.get(sim.id) != fighter_allegiance]

                        if opposing_targets:
                            victim = random.choice(opposing_targets)
                        else:
                            # Attack random civilian if no enemy soldiers
                            victim = random.choice([sim for sim in valid_targets if sim.id != fighter_sim.id])

                        if victim.id != fighter_sim.id:
                            context = interactions.context.InteractionContext(
                                fighter_sim,
                                interactions.context.InteractionContext.SOURCE_SCRIPT,
                                interactions.priority.Priority.High
                            )
                            fighter_sim.push_super_affordance(
                                fight_interaction,
                                victim,
                                context
                            )
                            sims4.commands.output(f"*** {fighter_sim.full_name} is engaging {victim.full_name} in combat! ***", sims4.commands.CheatOutput(_connection=None))

            # 10 second delay
            time_span = date_and_time.create_time_span(minutes=10) # 10 Sim minutes
            alarms.add_alarm(services.current_zone(), time_span, push_combat_interactions)

        else:
             sims4.commands.output("No off-lot Military Sims found to spawn for the skirmish.", sims4.commands.CheatOutput(_connection=None))

    except Exception as e:
        sims4.commands.output(f"Error running pure script skirmish: {e}", sims4.commands.CheatOutput(_connection=None))

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
        sims4.commands.output(f"REBELLION: {independence_forces} rebel forces are fighting for independence on the lot!", sims4.commands.CheatOutput(_connection=None))
    if dictatorship_forces > 0:
        sims4.commands.output(f"ENFORCEMENT: {dictatorship_forces} loyalist forces are suppressing the uprising!", sims4.commands.CheatOutput(_connection=None))

    # Base chance of casualties is 30%
    casualty_chance = 0.30

    # Rebels increase chance of ending the war in this zone, but also cause chaos
    if independence_forces > dictatorship_forces:
        casualty_chance += 0.20 # more intense fighting
        if random.random() < 0.40: # 40% chance the rebels win the zone immediately
            current_zone = services.current_zone()
            if current_zone and current_zone.region and current_zone.region.guid64 in active_war_zones:
                active_war_zones.remove(current_zone.region.guid64)
                sims4.commands.output(f"VICTORY! The independence fighters have liberated {current_zone.region.__name__}! Peace returns.", sims4.commands.CheatOutput(_connection=None))
                return # Skirmish ends early with peace
    elif dictatorship_forces > independence_forces:
        # Loyalists are brutal, they increase civilian casualty rate massively
        casualty_chance += 0.40
        sims4.commands.output("The loyalist forces are showing no mercy.", sims4.commands.CheatOutput(_connection=None))
    elif independence_forces > 0 and independence_forces == dictatorship_forces:
        # A bloody stalemate
        casualty_chance += 0.50
        sims4.commands.output("It's a chaotic stalemate between loyalists and rebels!", sims4.commands.CheatOutput(_connection=None))

    # Apply casualties
    if random.random() < casualty_chance:
        # Find a random sim on the lot who isn't the dictator
        valid_victims = []
        for sim in services.object_manager().get_valid_objects_gen():
            if sim.is_sim and sim.id != current_dictator_id:
                # If loyalists are in control, they target independence fighters first
                if dictatorship_forces > independence_forces and military_allegiances.get(sim.id) == "independence":
                    valid_victims.append(sim)
                    valid_victims.append(sim) # double weight
                # If rebels are in control, they target loyalists first
                elif independence_forces > dictatorship_forces and military_allegiances.get(sim.id) == "dictatorship":
                    valid_victims.append(sim)
                    valid_victims.append(sim) # double weight
                else:
                    valid_victims.append(sim)

        if valid_victims:
            victim = random.choice(valid_victims)
            sims4.commands.output(f"Oh no! {victim.full_name} was caught in the crossfire of the skirmish!", sims4.commands.CheatOutput(_connection=None))
            # Simulate injury or death. 10% base death, scales up slightly if high intensity
            death_chance = 0.1 + (0.1 if casualty_chance > 0.5 else 0.0)
            if random.random() < death_chance:
                sims4.commands.output(f"Tragically, {victim.full_name} did not survive.", sims4.commands.CheatOutput(_connection=None))
                victim.destroy()
            else:
                sims4.commands.output(f"{victim.full_name} was injured and evacuated.", sims4.commands.CheatOutput(_connection=None))
                # Treat like a 1-day jail
                time_span = date_and_time.create_time_span(days=1)
                alarm_handle = alarms.add_alarm(victim.sim_info, time_span, lambda _: _release_from_jail(victim.id))
                jailed_sims[victim.id] = alarm_handle
                victim.destroy()

def inject_method(target_class, target_function_name):
    """A basic injection decorator for Sims 4 modding."""
    def decorator(new_function):
        original_function = getattr(target_class, target_function_name)
        def wrapper(*args, **kwargs):
            return new_function(original_function, *args, **kwargs)
        setattr(target_class, target_function_name, wrapper)
        return wrapper
    return decorator

@inject_method(zone.Zone, 'do_zone_spin_up')
def _hook_zone_spin_up(original_function, self, *args, **kwargs):
    result = original_function(self, *args, **kwargs)

    global war_ticker_alarm, active_training_deployment
    # If the timer isn't running, start it. Ticks every 6 Sim hours.
    if war_ticker_alarm is None:
        time_span = date_and_time.create_time_span(hours=6)
        war_ticker_alarm = alarms.add_alarm(self, time_span, _war_ticker_callback, repeating=True)

    # Check if we just traveled for a training deployment
    if active_training_deployment is not None:
        sim_id = active_training_deployment
        active_training_deployment = None # Clear it so it only runs once per travel

        sim_info = services.sim_info_manager().get(sim_id)
        if sim_info is not None:
            # Delay the training actions slightly to let the world fully load
            time_span = date_and_time.create_time_span(minutes=5)
            alarms.add_alarm(self, time_span, lambda _: _start_training_regimen(sim_info.id))

    # Check if we just traveled into an active war zone. If so, immediately trigger a skirmish.
    global _traveling_to_force_war
    current_region = self.region if hasattr(self, 'region') else None

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
                    sims4.commands.output("DICTATORSHIP GRANT: This teen-only household has received 5,000 Simoleons to encourage independent living!", sims4.commands.CheatOutput(_connection=None))
                elif not all_teens:
                    # If it's a normal household, just mark it so we don't keep checking it every load screen
                    teen_households_granted.add(active_hh.id)

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

    interaction_manager = services.get_instance_manager(sims4.resources.Types.INTERACTION)

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
        interactions.priority.Priority.High
    )

    sims4.commands.output(f"MILITARY TRAINING: {sim_info.full_name} has arrived and is beginning their training regimen (Pushups, Jogging, Interrogating Locals).", sims4.commands.CheatOutput(_connection=None))

    # Push Pushups
    if pushups_sa is not None:
        # Pushups are targeted on the sim themselves or the ground. Usually None is fine for self-interactions.
        sim_instance.push_super_affordance(pushups_sa, None, context)

    # Push Jog (queues after pushups)
    if jog_sa is not None:
        sim_instance.push_super_affordance(jog_sa, None, context)

    # Find a random local to talk to
    if chat_sa is not None:
        valid_targets = [sim for sim in services.object_manager().get_valid_objects_gen() if sim.is_sim and sim.id != sim_id and sim.sim_info.age in (Age.TEEN, Age.YOUNGADULT, Age.ADULT, Age.ELDER)]
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
            sims4.commands.output(f"HEROIC RETURN: {sim_info.full_name} has survived the war and returned home! They have been awarded the Medal of Valor for their efforts.", sims4.commands.CheatOutput(_connection=None))

            # Apply the positive moodlet
            buff_manager = services.get_instance_manager(sims4.resources.Types.BUFF)
            survived_buff = buff_manager.get(SURVIVED_WAR_BUFF_ID)

            if survived_buff is not None:
                sim_info.add_buff_from_op(survived_buff.buff_type)
                sims4.commands.output(f"*** {sim_info.full_name} received a positive moodlet for surviving! ***", sims4.commands.CheatOutput(_connection=None))
        else:
            sims4.commands.output(f"Tragic news... {sim_info.full_name} was killed in action during the war.", sims4.commands.CheatOutput(_connection=None))
            # In a full mod, trigger actual death sequence. For prototype, we just leave them despawned/destroyed.
            sim_instance = sim_info.get_sim_instance()
            if sim_instance is not None:
                sim_instance.destroy()

@sims4.commands.Command('dictator.declare_war', command_type=sims4.commands.CommandType.Live)
def declare_war(_connection=None):
    """The Dictator manually declares war on a random world."""
    output = sims4.commands.CheatOutput(_connection)
    global current_dictator_id, active_war_zones

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
    output(f"The Dictator has declared WAR on {target_region.__name__}!")

    # If the active zone is now a war zone, trigger an immediate skirmish
    current_zone = services.current_zone()
    if current_zone is not None and current_zone.region is not None and current_zone.region.guid64 == target_region.guid64:
        _trigger_active_war_skirmish()

    return True

@sims4.commands.Command('dictator.travel_to_war', command_type=sims4.commands.CommandType.Live)
def travel_to_war(_connection=None):
    """Forces the Dictator and the active household/camera to travel to a random active war zone."""
    output = sims4.commands.CheatOutput(_connection)

    global current_dictator_id, active_war_zones

    if current_dictator_id is None:
        output("There is no Dictator to travel.")
        return False

    current_zone_id = services.current_zone_id()
    current_zone = services.current_zone()
    current_region_id = current_zone.region.guid64 if (current_zone and current_zone.region) else None

    # Get all active wars that are NOT the current zone
    offscreen_wars = [r_id for r_id in active_war_zones if r_id != current_region_id]

    if not offscreen_wars:
        output("There are no active wars happening in other regions to travel to.")
        return False

    destination_region_id = random.choice(offscreen_wars)

    # Pick a random lot in the destination region
    import build_buy
    from server.client import Client

    all_zones = services.get_persistence_service().get_save_game_data_proto().zones
    valid_destinations = []
    region_manager = services.get_instance_manager(sims4.resources.Types.REGION)
    destination_region = region_manager.get(destination_region_id)

    if destination_region is None:
        output(f"Could not resolve the region for the war zone (ID {destination_region_id}).")
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

    output(f"The Dictator is traveling to the front lines! Loading screen incoming...")

    # Force travel for the active household
    client = services.client_manager().get_first_client()
    if client is not None:
        active_household = client.household
        if active_household is not None:
            travel_sim_ids = list(active_household.sim_ids)

            global _traveling_to_force_war
            _traveling_to_force_war = True

            # Trigger the game's travel sequence
            services.get_zone_situation_manager()._travel_to_zone(destination_zone_id, travel_sim_ids)

    return True

@sims4.commands.Command('dictator.deploy_training', command_type=sims4.commands.CommandType.Live)
def deploy_training(opt_target: OptionalTargetParam = None, _connection=None):
    """Forces the target military Sim (and the active household/camera) to travel to a random region for training."""
    output = sims4.commands.CheatOutput(_connection)
    target_sim = get_optional_target(opt_target, _connection)
    global active_training_deployment

    if target_sim is None:
        output("No target found for training deployment.")
        return False

    # Pick a random lot in the world that isn't the current one to travel to
    import build_buy
    from server.client import Client

    current_zone_id = services.current_zone_id()
    all_zones = services.get_persistence_service().get_save_game_data_proto().zones

    valid_destinations = [z.zone_id for z in all_zones if z.zone_id != current_zone_id]

    if not valid_destinations:
        output("Could not find another zone to travel to for training.")
        return False

    destination_zone_id = random.choice(valid_destinations)

    output(f"Deploying {target_sim.full_name} to a foreign region for active training! Loading screen incoming...")

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
            services.get_zone_situation_manager()._travel_to_zone(destination_zone_id, travel_sim_ids)

    return True

@sims4.commands.Command('dictator.draft_sim', command_type=sims4.commands.CommandType.Live)
def draft_sim(opt_target: OptionalTargetParam = None, _connection=None):
    """The Dictator drafts a Sim into the military to fight in a random active warzone."""
    output = sims4.commands.CheatOutput(_connection)
    target_sim = get_optional_target(opt_target, _connection)

    global current_dictator_id, drafted_sims, active_war_zones

    if current_dictator_id is None:
        output("There is no Dictator in power to declare war or draft Sims.")
        return False

    if not active_war_zones:
        output("There are no active wars! Sims cannot be drafted during peacetime.")
        return False

    if target_sim is None:
        output("No target found to draft.")
        return False

    if target_sim.id == current_dictator_id:
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
            output(f"{target_sim.full_name} is an infant, but their exceptional skills qualify them for the draft!")
        else:
            output(f"{target_sim.full_name} is an infant and lacks the required maxed skills to be drafted.")
            return False
    else:
        output(f"{target_sim.full_name} is not an eligible age for the military draft.")
        return False

    if is_eligible:
        # Draft them for a random amount of time between 2 and 5 days
        draft_duration_days = random.randint(2, 5)
        output(f"By decree of the Dictator, {target_sim.full_name} has been drafted and sent to the warzone for {draft_duration_days} Sim days!")

        time_span = date_and_time.create_time_span(days=draft_duration_days)
        alarm_handle = alarms.add_alarm(sim_info, time_span, lambda _: _return_from_war(sim_info.id))
        drafted_sims[sim_info.id] = alarm_handle

        # Despawn the Sim to simulate them leaving for war
        target_sim.destroy()
        return True

# --- Interaction Hooks for Voting Board ---

import interactions.base.super_interaction
from event_testing.results import TestResult

@inject_method(interactions.base.super_interaction.SuperInteraction, 'test')
def _hook_super_interaction_test(original_function, self, *args, **kwargs):
    result = original_function(self, *args, **kwargs)

    # If the test passed naturally, we just return it.
    if result:
        return result

    global current_dictator_id
    if current_dictator_id is None:
        return result

    # kwargs usually has 'context' from which we can get the interacting sim
    context = kwargs.get('context')
    if context is None and args:
        # Sometimes context is the first arg if it's not a kwarg
        context = args[0]

    if context is not None and getattr(context, 'sim', None) is not None:
        sim = context.sim
        if sim.id == current_dictator_id:
            # We check if the interaction belongs to NAP voting boards/mailboxes.
            # Interactions related to NAPs usually contain 'civic_policy' or 'voting' in their tuning name.
            # In Sims 4, `self.__name__` or `type(self).__name__` gives the tuning name.
            interaction_name = type(self).__name__.lower()
            if 'civic_policy' in interaction_name or 'voting' in interaction_name or 'nap' in interaction_name:
                # Override the test failure! The Dictator can do what they want, even if they are an infant.
                return TestResult.TRUE

    return result

@sims4.commands.Command('dictator.illegal_vote', command_type=sims4.commands.CommandType.Live)
def illegal_vote(opt_target: OptionalTargetParam = None, _connection=None):
    """Simulates the consequence of a Sim trying to vote while a Dictator is in power."""
    output = sims4.commands.CheatOutput(_connection)
    target_sim = get_optional_target(opt_target, _connection)

    global current_dictator_id

    if current_dictator_id is None:
        output("There is no Dictator in power, so voting is allowed.")
        return True

    if target_sim is None:
        output("No target found for illegal voting.")
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
        output(f"{target_sim.full_name} tried to vote illegally! The Military has arrested them and sent them to jail for 3 Sim days.")
        # Simulating jail by despawning the instantiated Sim
        if target_sim is not None:
            target_sim.destroy()
    elif sim_info.age in (Age.BABY, Age.INFANT, Age.TODDLER, Age.CHILD):
        # Consequence: Adopted into another household
        # Find another household in the world
        household_manager = services.household_manager()
        eligible_households = [hh for hh in household_manager.values()
                               if hh.id != sim_info.household.id and hh.home_zone_id != 0 and len(hh.sim_info_gen()) < 8]

        if eligible_households:
            adoptive_household = random.choice(eligible_households)
            # Remove from current household and add to new one
            current_household = sim_info.household
            if current_household is not None:
                current_household.remove_sim_info(sim_info)

            adoptive_household.add_sim_info(sim_info)
            output(f"Because the family committed treason by trying to vote, the child {target_sim.full_name} has been taken away and adopted by the {adoptive_household.name} household!")

            # despawn the sim object on current lot so they "leave"
            if target_sim is not None:
                target_sim.destroy()
        else:
            output(f"Could not find an eligible household to adopt the child {target_sim.full_name}.")
            # Fallback consequence if adoption fails
            if target_sim is not None:
                target_sim.destroy()
    else:
        output(f"Unknown age for {target_sim.full_name}.")

    return True
