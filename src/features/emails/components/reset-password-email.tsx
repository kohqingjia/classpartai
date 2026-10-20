import { Button, Section, Text } from "@react-email/components";
import { Layout } from "./layout";

interface ResetPasswordEmailProps {
  url: string;
  user: { email: string };
}

export const ResetPasswordEmail = ({ url, user }: ResetPasswordEmailProps) => {
  return (
    <Layout previewText="Reset your password">
      <Section>
        <Text style={h1}>Password Reset Request</Text>
        <Text style={text}>
          Hi there,
          <br />
          <br />
          We received a request to reset the password for your account ({user.email}). If this was
          you, click the button below to set a new password.
        </Text>
        <Button href={url} style={button}>
          Reset Your Password
        </Button>
        <Text style={subtext}>
          If you did not request a password reset, please ignore this email. Your password will not
          be changed.
          <br />
          <br />
          This link will expire in 1 hour.
        </Text>
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

const subtext = {
  color: "#6b7280",
  fontSize: "14px",
  lineHeight: "20px",
  margin: "24px 0 0",
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
