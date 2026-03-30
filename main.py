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
        else:
            output("Error: Could not load the fight interaction data.")
    except Exception as e:
        output(f"Error pushing fight interaction: {e}")

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
    """A skirmish happens on the active lot because it's in a war zone."""
    global current_dictator_id, military_allegiances, active_war_zones
    sims4.commands.output("WARNING: The active neighborhood is a WAR ZONE! A skirmish has erupted!", sims4.commands.CheatOutput(_connection=None))

    # Assess allegiances of military Sims on the lot
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

    global war_ticker_alarm
    # If the timer isn't running, start it. Ticks every 6 Sim hours.
    if war_ticker_alarm is None:
        time_span = date_and_time.create_time_span(hours=6)
        war_ticker_alarm = alarms.add_alarm(self, time_span, _war_ticker_callback, repeating=True)

    return result

def _return_from_war(sim_id):
    """Callback function when a drafted Sim returns from war."""
    global drafted_sims
    sim_info_manager = services.sim_info_manager()
    sim_info = sim_info_manager.get(sim_id)

    if sim_id in drafted_sims:
        del drafted_sims[sim_id]

    if sim_info is not None:
        # Randomly decide if they survived. For a prototype, let's say 80% survival rate.
        if random.random() < 0.8:
            sims4.commands.output(f"{sim_info.full_name} has survived the war and returned home!", sims4.commands.CheatOutput(_connection=None))
            # In a full mod, apply a PTSD/Tense or Confident buff here.
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

    # Check age to see if they are eligible for the draft
    if sim_info.age in (Age.TEEN, Age.YOUNGADULT, Age.ADULT, Age.ELDER):
        # Draft them for a random amount of time between 2 and 5 days
        draft_duration_days = random.randint(2, 5)
        output(f"By decree of the Dictator, {target_sim.full_name} has been drafted and sent to the warzone for {draft_duration_days} Sim days!")

        time_span = date_and_time.create_time_span(days=draft_duration_days)
        alarm_handle = alarms.add_alarm(sim_info, time_span, lambda _: _return_from_war(sim_info.id))
        drafted_sims[sim_info.id] = alarm_handle

        # Despawn the Sim to simulate them leaving for war
        target_sim.destroy()
        return True
    else:
        output(f"{target_sim.full_name} is too young to be drafted into the military.")
        return False

# --- Interaction Hooks for Voting Board ---
# To make this a full mod instead of just a prototype command, you would inject into the
# specific interaction tuning for the NAP voting boards.
# For example, injecting into `civic_policies_voting_board_interactions`.
# When the interaction is tested or triggered, you check `current_dictator_id`.
# If it's not None, you cancel the interaction and call the logic below.

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
