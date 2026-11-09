import type { Metadata } from "next";
import { Bricolage_Grotesque, Hanken_Grotesk, JetBrains_Mono } from "next/font/google";

import "./globals.css";

const hanken = Hanken_Grotesk({ variable: "--font-hanken", subsets: ["latin"] });
const bricolage = Bricolage_Grotesque({ variable: "--font-bricolage", subsets: ["latin"] });
const jetbrains = JetBrains_Mono({ variable: "--font-jetbrains", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "ShipReady", template: "%s · ShipReady" },
  description: "Checks an export shipment's documents against each other before customs does.",
};

// The theme a person picked in the sidebar, applied before the first paint so the page does not
// flash the other theme. Without a choice the system's applies (globals.css).
const applyTheme = `try{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${hanken.variable} ${bricolage.variable} ${jetbrains.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script id="apply-theme" dangerouslySetInnerHTML={{ __html: applyTheme }} />
      </head>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
