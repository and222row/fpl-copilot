import { router } from 'expo-router';

import { Button } from '@/components/button';
import { Banner } from '@/components/screen';

/**
 * FPL only publishes a squad once its gameweek starts, so before a deadline
 * the advice is about the last locked squad. Worth knowing; not worth the half
 * screen the server's full explanation takes, so it starts collapsed, with the
 * fix one tap away.
 */
export function SquadBanner({ warning }: { warning: string | null | undefined }) {
  if (!warning) return null;
  const gw = warning.match(/GW(\d+)/)?.[1];
  return (
    <Banner
      testID="squad-banner"
      title={gw ? `Based on your GW${gw} squad` : 'Based on your last locked squad'}
      detail={warning}
      action={
        <Button title="Record transfers I made" variant="secondary" compact onPress={() => router.push('/record-transfers')} />
      }
    />
  );
}
