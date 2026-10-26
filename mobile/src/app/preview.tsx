import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { errorMessage } from '@/components/error-view';
import { Card, Pill, Screen, SectionHeader } from '@/components/screen';
import { Stat, StatRow } from '@/components/stat';
import { TextField } from '@/components/text-field';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import { api, type TeamPreview } from '@/lib/api';

/**
 * Try before signing up: a Team ID in, a taste of the advice out. The server
 * shows only FPL's public data and how much the advice gains, keeping the
 * players behind sign-in, so nothing here needs an account.
 */
export default function Preview() {
  const [value, setValue] = useState('');
  const [teamId, setTeamId] = useState<number | null>(null);
  const valid = /^\d{1,9}$/.test(value) ? Number(value) : null;
  const preview = useQuery({
    queryKey: ['preview', teamId],
    queryFn: () => api.preview(teamId!),
    enabled: teamId !== null,
    staleTime: 30 * 60_000,
    retry: false,
  });

  return (
    <Screen
      belowHeader
      testID="preview-screen"
      footer={<Button testID="preview-sign-in" title="Sign in: 30 days free" onPress={() => router.back()} />}>
      {!preview.data ? (
        <>
          <ThemedText type="subtitle">See what we&apos;d tell you</ThemedText>
          <ThemedText type="small" themeColor="textSecondary">
            Enter your FPL Team ID. You&apos;ll find it on the FPL website, in the address bar on the Points page.
          </ThemedText>
          <TextField
            large
            testID="preview-input"
            value={value}
            onChangeText={(t) => setValue(t.replace(/\D/g, ''))}
            onSubmitEditing={() => valid && setTeamId(valid)}
            placeholder="1234567"
            keyboardType="number-pad"
            returnKeyType="go"
            maxLength={9}
            accessibilityLabel="FPL Team ID"
          />
          <Button
            testID="preview-go"
            title="Show me"
            variant="secondary"
            disabled={!valid}
            loading={preview.isFetching}
            onPress={() => valid && setTeamId(valid)}
          />
          {preview.isFetching ? (
            <ThemedText type="caption" themeColor="textSecondary">
              Working out your best moves. This can take a few seconds.
            </ThemedText>
          ) : null}
          {preview.isError ? (
            <ThemedText testID="preview-error" themeColor="danger" accessibilityRole="alert">
              {errorMessage(preview.error)}
            </ThemedText>
          ) : null}
        </>
      ) : (
        <Result data={preview.data} onAgain={() => setTeamId(null)} />
      )}
    </Screen>
  );
}

function Result({ data, onAgain }: { data: TeamPreview; onAgain: () => void }) {
  const theme = useTheme();
  const t = data.teaser;
  return (
    <>
      <Card variant="hero">
        <ThemedText type="eyebrow" style={{ color: theme.brand }}>
          {data.team.manager}
        </ThemedText>
        <ThemedText type="subtitle" style={{ color: theme.onHero }}>
          {data.team.name}
        </ThemedText>
        <StatRow>
          <Stat onHero label="Overall rank" value={data.team.overall_rank ? data.team.overall_rank.toLocaleString() : '—'} />
          <Stat onHero label="Points" value={data.team.total_points !== null ? String(data.team.total_points) : '—'} />
          <Stat onHero label="Last GW" value={data.team.last_gameweek_points !== null ? String(data.team.last_gameweek_points) : '—'} />
        </StatRow>
      </Card>

      <SectionHeader title={`For ${data.gameweek.name}`} />
      <Card testID="preview-teaser">
        {t.transfers > 0 ? (
          <ThemedText type="headline">
            We found {t.transfers === 1 ? 'a transfer' : `${t.transfers} transfers`} worth +{t.gain.toFixed(1)} points over the next{' '}
            {t.horizon ?? 5} gameweeks{t.hit ? `, after the −${t.hit} hit` : ''}.
          </ThemedText>
        ) : (
          <ThemedText type="headline">Your team is in good shape: we&apos;d roll the transfer this week.</ThemedText>
        )}
        <ThemedText type="small" themeColor="textSecondary">
          Your best XI ({t.formation}) projects {t.projected.toFixed(1)} points, with the captain we&apos;d pick.
        </ThemedText>
        <View style={styles.locked}>
          <Pill label="Locked" color="accent" soft="accentSoft" />
          <ThemedText type="small" themeColor="textSecondary" style={styles.grow}>
            Who to sell, who to buy and who to captain unlock when you sign in.
          </ThemedText>
        </View>
      </Card>

      {data.flagged.length > 0 ? (
        <>
          <SectionHeader title={`Flagged in your squad · ${data.flagged.length}`} />
          <Card>
            {data.flagged.map((f) => (
              <ThemedText key={f.name} type="small">
                <ThemedText type="smallBold">{f.name}</ThemedText> · {f.news || f.reason}
              </ThemedText>
            ))}
          </Card>
        </>
      ) : null}

      <ThemedText type="smallBold" themeColor="accent" accessibilityRole="button" onPress={onAgain} style={styles.again}>
        Try another Team ID
      </ThemedText>
    </>
  );
}

const styles = StyleSheet.create({
  locked: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two, marginTop: Spacing.one },
  again: { textAlign: 'center' },
  grow: { flex: 1 },
});
