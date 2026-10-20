import * as React from "react";
import { Body, Container, Head, Hr, Html, Preview, Section, Text } from "@react-email/components";

interface LayoutProps {
  previewText?: string;
  children: React.ReactNode;
}

export const Layout = ({ previewText, children }: LayoutProps) => {
  return (
    <Html>
      <Head />
      <Preview>{previewText || ""}</Preview>
      <Body style={main}>
        <Container style={container}>
          <Section style={header}>
            <Text style={logo}>TanStack Start</Text>
          </Section>
          <Section style={content}>{children}</Section>
          <Hr style={hr} />
          <Section style={footer}>
            <Text style={footerText}>Sent from TanStack Start Template.</Text>
          </Section>
        </Container>
      </Body>
    </Html>
  );
};

const main = {
  backgroundColor: "#ffffff",
  fontFamily:
    '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Oxygen-Sans,Ubuntu,Cantarell,"Helvetica Neue",sans-serif',
};

const container = {
  margin: "0 auto",
  padding: "20px 0 48px",
  maxWidth: "580px",
};

const header = {
  padding: "32px 0",
};

const logo = {
  fontSize: "24px",
  fontWeight: "700",
  letterSpacing: "-0.02em",
  color: "#000000",
  margin: "0",
};

const content = {
  padding: "0 0 32px",
};

const hr = {
  borderColor: "#e5e7eb",
  margin: "20px 0",
};

const footer = {
  padding: "0 0 32px",
};

const footerText = {
  color: "#6b7280",
  fontSize: "12px",
  lineHeight: "16px",
};
