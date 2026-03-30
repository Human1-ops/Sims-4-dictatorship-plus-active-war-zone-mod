import sims4.commands
import services

@sims4.commands.Command('dictator.declare', command_type=sims4.commands.CommandType.Live)
def declare_dictator(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    output("The current Sim has been declared the Supreme Leader!")
    output("A new era of prosperity (and absolute control) begins now.")

@sims4.commands.Command('dictator.tax', command_type=sims4.commands.CommandType.Live)
def collect_taxes(amount: int=1000, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    try:
        client = services.client_manager().get(_connection)
        if client is not None and client.active_sim is not None:
            household = client.active_sim.household
            # Attempt to add funds to the active household
            household.funds.add(amount, 0, None)
            output(f"Taxes collected! The state treasury (your household) has received {amount} Simoleons.")
        else:
            output("Could not find an active Sim or household.")
    except Exception as e:
        output("An error occurred while collecting taxes.")
        output(str(e))

@sims4.commands.Command('dictator.arrest', command_type=sims4.commands.CommandType.Live)
def arrest_sim(sim_first_name: str, sim_last_name: str, _connection=None):
    output = sims4.commands.CheatOutput(_connection)
    output(f"Warrant issued for {sim_first_name} {sim_last_name}.")
    output("The secret police have been dispatched. (Feature coming soon)")

@sims4.commands.Command('dictator.propaganda', command_type=sims4.commands.CommandType.Live)
def broadcast_propaganda(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    output("Broadcasting state propaganda...")
    output("All Sims in the neighborhood are now 'Inspired' by the Supreme Leader's vision. (Feature coming soon)")
