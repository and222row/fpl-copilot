import { router } from 'expo-router';

import { api } from '@/lib/api';
import { refreshAccount } from '@/lib/query';

/**
 * Begin proving a team is yours: get the code to put in its name, then open
 * the screen that checks for it.
 *
 * One path for all three reasons to prove: taking over a team another account
 * holds, starting the trial right after connecting by ID, and starting it
 * later from the paywall. The `prove` route is reachable in every signed-in
 * state, so connecting a team — which changes that state — cannot strand the
 * user halfway through.
 */
export async function proveTeam(teamId: number): Promise<void> {
  const result = await api.claimConnection(teamId);
  if (result.status === 'connected') {
    // Already proven: nothing to do but pick up the current state.
    await refreshAccount();
    return;
  }
  router.push({
    pathname: '/prove',
    params: { teamId: String(result.fpl_entry_id), code: result.code, teamName: result.team_name },
  });
}
