import * as Sharing from 'expo-sharing';
import { useRef, useState, type Ref } from 'react';
import { Alert, Modal, StyleSheet, View } from 'react-native';
import { captureRef } from 'react-native-view-shot';

import { Button } from '@/components/button';
import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { reportError } from '@/lib/monitoring';
import type { CardContent } from '@/lib/share-card';

// Brand colours, fixed: the card is an image and must look the same whatever
// the phone's light or dark setting.
const PURPLE = '#37003C';
const PURPLE_DEEP = '#28002C';
const GREEN = '#00FF87';
const CYAN = '#04F5FF';
const WHITE = '#FFFFFF';
const MUTED = 'rgba(255,255,255,0.72)';

// Drawn at 320x400 points and saved at 1080x1350 pixels: 4:5 portrait, the
// shape Instagram and WhatsApp show without cropping.
const CARD_WIDTH = 320;
const CARD_HEIGHT = 400;
export const IMAGE_SIZE = { width: 1080, height: 1350 };

/** The card itself: what gets turned into an image. */
export function ShareCardView({ card, ref }: { card: CardContent; ref?: Ref<View> }) {
  return (
    <View ref={ref} collapsable={false} style={styles.card} testID="share-card">
      <View style={styles.glow} />
      <ThemedText style={styles.brand}>FPL COPILOT</ThemedText>
      <View style={styles.body}>
        <ThemedText style={styles.eyebrow} numberOfLines={1}>
          {card.eyebrow}
        </ThemedText>
        <ThemedText style={styles.team} numberOfLines={1}>
          {card.team}
        </ThemedText>
        <ThemedText style={styles.big}>{card.big}</ThemedText>
        {card.sub ? <ThemedText style={styles.sub}>{card.sub}</ThemedText> : null}
      </View>
      <View style={styles.stats}>
        {card.stats.map((s) => (
          <View key={s.label} style={styles.stat}>
            <ThemedText style={styles.statValue} numberOfLines={1}>
              {s.value}
            </ThemedText>
            <ThemedText style={styles.statLabel}>{s.label}</ThemedText>
          </View>
        ))}
      </View>
      {card.lines.map((line) => (
        <ThemedText key={line} style={styles.line} numberOfLines={1}>
          {line}
        </ThemedText>
      ))}
      <ThemedText style={styles.footer}>Your FPL, worked out · fplcopilot</ThemedText>
    </View>
  );
}

/**
 * A "Share" button: shows the card, then saves it as an image and opens the
 * share sheet. Nothing leaves the phone unless the user picks an app.
 */
export function ShareCardButton({ card, title = 'Share' }: { card: CardContent | null; title?: string }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef<View>(null);

  async function share() {
    if (!ref.current) return;
    setBusy(true);
    try {
      if (!(await Sharing.isAvailableAsync())) {
        Alert.alert('Sharing is not available on this device.');
        return;
      }
      const uri = await captureRef(ref, { format: 'png', quality: 1, result: 'tmpfile', ...IMAGE_SIZE });
      await Sharing.shareAsync(uri, { mimeType: 'image/png', UTI: 'public.png', dialogTitle: 'Share your card' });
      setOpen(false);
    } catch (e) {
      reportError(e);
      Alert.alert("Couldn't make the image", 'Please try again.');
    } finally {
      setBusy(false);
    }
  }

  if (!card) return null;
  return (
    <>
      <Button testID="share-open" title={title} variant="secondary" compact onPress={() => setOpen(true)} />
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <View style={styles.backdrop}>
          <ShareCardView card={card} ref={ref} />
          <View style={styles.actions}>
            <Button testID="share-send" title="Share image" onPress={share} loading={busy} />
            <Button title="Close" variant="secondary" onPress={() => setOpen(false)} />
          </View>
        </View>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  card: {
    width: CARD_WIDTH,
    height: CARD_HEIGHT,
    borderRadius: 24,
    backgroundColor: PURPLE,
    padding: 24,
    overflow: 'hidden',
    justifyContent: 'space-between',
  },
  glow: {
    position: 'absolute',
    right: -80,
    top: -80,
    width: 240,
    height: 240,
    borderRadius: 120,
    backgroundColor: PURPLE_DEEP,
    borderWidth: 18,
    borderColor: 'rgba(4,245,255,0.18)',
  },
  brand: { color: GREEN, fontSize: 12, lineHeight: 16, fontWeight: '900', letterSpacing: 2 },
  body: { gap: 2 },
  eyebrow: { color: CYAN, fontSize: 13, lineHeight: 18, fontWeight: '700' },
  team: { color: WHITE, fontSize: 18, lineHeight: 24, fontWeight: '800' },
  big: { color: WHITE, fontSize: 64, lineHeight: 72, fontWeight: '900', fontVariant: ['tabular-nums'] },
  sub: { color: GREEN, fontSize: 15, lineHeight: 20, fontWeight: '700' },
  stats: { flexDirection: 'row', gap: 12, borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.18)', paddingTop: 12 },
  stat: { flex: 1, gap: 2 },
  statValue: { color: WHITE, fontSize: 16, lineHeight: 20, fontWeight: '800' },
  statLabel: { color: MUTED, fontSize: 11, lineHeight: 14, fontWeight: '600' },
  line: { color: WHITE, fontSize: 14, lineHeight: 18, fontWeight: '600' },
  footer: { color: MUTED, fontSize: 11, lineHeight: 14, fontWeight: '600' },
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.75)',
    alignItems: 'center',
    justifyContent: 'center',
    gap: Spacing.four,
    padding: Spacing.four,
  },
  actions: { width: CARD_WIDTH, gap: Spacing.two },
});
