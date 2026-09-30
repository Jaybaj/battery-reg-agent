// Formatted in UTC so an ISO date ("2027-02-18") never shifts a day in the viewer's timezone.
const LONG_DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });

export function formatIsoDate(iso: string): string {
  return LONG_DATE.format(new Date(`${iso}T00:00:00Z`));
}
