import { Section, Text } from "@react-email/components";
import { Layout } from "./layout";

interface OtpEmailProps {
  otp: string;
  type: "sign-in" | "email-verification" | "forget-password" | "change-email";
}

export const OtpEmail = ({ otp, type }: OtpEmailProps) => {
  const isVerification = type === "email-verification";
  return (
    <Layout previewText={isVerification ? "Verify your email" : "Your sign-in code"}>
      <Section>
        <Text style={h1}>
          {isVerification ? "Welcome to TanStack Start!" : "Sign in to TanStack Start"}
        </Text>
        <Text style={text}>
          {isVerification
            ? "Thanks for signing up! Use the code below to verify your email address."
            : "Use the code below to sign in to your account."}
        </Text>
        <Text style={code}>{otp}</Text>
        <Text style={hint}>This code expires in 10 minutes.</Text>
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

const code = {
  backgroundColor: "#f3f4f6",
  borderRadius: "8px",
  color: "#000000",
  fontSize: "36px",
  fontWeight: "700",
  letterSpacing: "8px",
  padding: "16px 24px",
  textAlign: "center" as const,
  margin: "0 0 16px",
};

const hint = {
  color: "#9ca3af",
  fontSize: "14px",
  lineHeight: "20px",
  margin: "0",
};
