import { useState, type ReactNode } from 'react';
import { Pressable, ScrollView, StyleSheet, View, type LayoutChangeEvent } from 'react-native';

import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

/**
 * Swipeable pages, one at a time, with dots underneath. Pages size to the
 * carousel's own width, so it works inside a padded screen as well as edge
 * to edge.
 */
export function Carousel({
  pages,
  testID,
  onIndexChange,
}: {
  pages: ReactNode[];
  testID?: string;
  onIndexChange?: (index: number) => void;
}) {
  const theme = useTheme();
  const [width, setWidth] = useState(0);
  const [index, setIndex] = useState(0);
  const [scroller, setScroller] = useState<ScrollView | null>(null);

  function onLayout(e: LayoutChangeEvent) {
    setWidth(e.nativeEvent.layout.width);
  }

  function settle(x: number) {
    if (!width) return;
    const next = Math.round(x / width);
    if (next !== index) {
      setIndex(next);
      onIndexChange?.(next);
    }
  }

  function goTo(i: number) {
    scroller?.scrollTo({ x: i * width, animated: true });
    setIndex(i);
    onIndexChange?.(i);
  }

  return (
    <View testID={testID} onLayout={onLayout}>
      <ScrollView
        ref={setScroller}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onMomentumScrollEnd={(e) => settle(e.nativeEvent.contentOffset.x)}
        scrollEventThrottle={16}>
        {pages.map((page, i) => (
          <View key={i} style={{ width: width || undefined }} accessibilityLabel={`Page ${i + 1} of ${pages.length}`}>
            <View style={styles.page}>{page}</View>
          </View>
        ))}
      </ScrollView>
      {pages.length > 1 ? (
        <View style={styles.dots} accessibilityRole="tablist">
          {pages.map((_, i) => (
            <Pressable
              key={i}
              accessibilityRole="button"
              accessibilityLabel={`Show page ${i + 1}`}
              accessibilityState={{ selected: i === index }}
              hitSlop={8}
              onPress={() => goTo(i)}
              style={[
                styles.dot,
                { backgroundColor: i === index ? theme.accent : theme.hairline, width: i === index ? 18 : 7 },
              ]}
            />
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  page: { paddingHorizontal: 2 },
  dots: { flexDirection: 'row', justifyContent: 'center', gap: 6, marginTop: Spacing.two },
  dot: { height: 7, borderRadius: 4 },
});
