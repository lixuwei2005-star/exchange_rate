/**
 * Small brand icon shown to the left of a channel name in the rate table.
 *
 * Each icon is the provider's own site favicon (the thing you see next to the
 * page title in a browser tab), downloaded once at build time into
 * `public/channels/` and self-hosted. We never hit a third-party favicon
 * service at runtime — CLAUDE.md §13 requires zero third-party requests.
 * (BOC is a hand-drawn SVG of its coin logo because its favicon services only
 * expose a blurry placeholder.)
 *
 * The three mid-market references (midmarket/2/3) are accounting values with
 * no brand, so they render a blank slot of the same width to keep every
 * channel name left-aligned.
 */
const LOGO_FILES: Record<string, string> = {
  wise: "wise.png",
  visa: "visa.png",
  mastercard: "mastercard.png",
  boc: "boc.png",
  icbc: "icbc.png",
  unionpay: "unionpay.png",
  publicbank: "publicbank.png",
  cimb: "cimb.png",
  maybank: "maybank-seeklogo.png",
  rhb: "rhb.png",
  hlb: "hong-leong-bank-seeklogo.png",
  alliance: "alliance-bank-seeklogo.png",
  ambank: "ambank.png",
  hsbc: "hsbc.png",
  ocbc: "ocbc.png",
  sc: "sc.png",
  affin: "affin.png",
};

export default function ChannelLogo({ code }: { code: string }) {
  const file = LOGO_FILES[code];
  // The three mid-market references have no brand → render nothing (the logo
  // sits to the right of the name, so no spacer is needed for alignment).
  if (!file) return null;
  return (
    // Self-hosted brand logo; next/image optimization is pointless overhead here.
    // Height-locked, width auto so wide wordmark logos keep their aspect ratio.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={`/channels/${file}`}
      alt=""
      loading="lazy"
      className="h-5 w-auto max-w-[84px] shrink-0 object-contain"
    />
  );
}
