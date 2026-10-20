import { Button, Section, Text } from "@react-email/components";
import { Layout } from "./layout";

interface VerificationEmailProps {
  url: string;
}

export const VerificationEmail = ({ url }: VerificationEmailProps) => {
  return (
    <Layout previewText="Verify your email address">
      <Section>
        <Text style={h1}>Welcome to TanStack Start!</Text>
        <Text style={text}>
          Thanks for signing up! we're excited to have you join our community. Please click the
          button below to verify your email address and get started.
        </Text>
        <Button href={url} style={button}>
          Verify Email Address
        </Button>
      </Section>
    </Layout>
  );
};

const h1 = {
  color: "#000000",
  fontSize: "24px",
  fontWeight: "600",
  lineHeight: "32px",
  margin: "0 0 20px",
};

const text = {
  color: "#4b5563",
  fontSize: "16px",
  lineHeight: "24px",
  margin: "0 0 24px",
};

const button = {
  backgroundColor: "#000000",
  borderRadius: "6px",
  color: "#ffffff",
  fontSize: "14px",
  fontWeight: "600",
  textDecoration: "none",
  textAlign: "center" as const,
  display: "block",
  width: "fit-content",
  padding: "12px 24px",
};
