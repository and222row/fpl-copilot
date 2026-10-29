import { render, screen, userEvent } from '@testing-library/react-native';

import { Loading } from '@/components/loading';
import { ToolGrid } from '@/components/tool-grid';

jest.mock('expo-symbols', () => ({ SymbolView: ({ fallback }: { fallback: unknown }) => fallback }));

test('tools are grouped tiles, each with a title, a line and an icon', async () => {
  const user = userEvent.setup();
  const opened: string[] = [];
  const tool = (testID: string, title: string) => ({
    testID, title, subtitle: `About ${title}`, icon: { ios: 'star.fill', android: 'star' }, onPress: () => opened.push(testID),
  });
  await render(
    <ToolGrid groups={[
      { title: 'This gameweek', tools: [tool('tool-live', 'Live gameweek'), tool('tool-review', 'Gameweek review')] },
      { title: 'Plan ahead', tools: [tool('tool-trends', 'Transfer trends')] },
    ]} />,
  );
  expect(screen.getByText('This gameweek')).toBeTruthy();
  expect(screen.getByText('Plan ahead')).toBeTruthy();
  expect(screen.getByLabelText('Transfer trends. About Transfer trends')).toBeTruthy();
  await user.press(screen.getByTestId('tool-review'));
  expect(opened).toEqual(['tool-review']);
});

test('loading is a spinner, with a line only when one is given', async () => {
  await render(<Loading />);
  expect(screen.getByLabelText('Loading')).toBeTruthy();
  await render(<Loading label="Reading your rivals' squads…" />);
  expect(screen.getByText("Reading your rivals' squads…")).toBeTruthy();
});
