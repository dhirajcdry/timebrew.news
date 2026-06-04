import React, {
	createContext,
	useContext,
	useState,
	useEffect,
	ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import {
	signIn,
	signOut,
	confirmSignIn,
	confirmSignUp,
	getCurrentUser,
	fetchUserAttributes,
	fetchAuthSession,
} from "aws-amplify/auth";
import "@/config/amplify"; // Initialize Amplify configuration

// Define types for our context
interface User {
	id: string;
	email: string;
	firstName: string;
	lastName: string;
	country: string;
	interests: string[];
	timezone: string;
	createdAt: string;
}

interface AuthContextType {
	user: User | null;
	isAuthenticated: boolean;
	isLoading: boolean;
	logout: () => void;
	updateUser: (userData: Partial<User>) => void;
	getAccessToken: () => Promise<string | null>;
	refreshToken: () => Promise<string | null>;
	// OTP flow methods
	initiateLogin: (
		email: string
	) => Promise<{ success: boolean; error?: string; session?: string }>;
	verifyOTP: (
		otp: string,
		session?: any
	) => Promise<{ success: boolean; error?: string }>;
	register: (
		email: string,
		firstName: string,
		lastName: string,
		country?: string,
		interests?: string[],
		timezone?: string
	) => Promise<{ success: boolean; error?: string }>;
	verifyRegistration: (
		email: string,
		otp: string
	) => Promise<{ success: boolean; error?: string }>;
	resendOTP: (
		email: string
	) => Promise<{ success: boolean; error?: string; session?: string }>;
}

interface AuthProviderProps {
	children: ReactNode;
}

// Create the context with a default value
const AuthContext = createContext<AuthContextType | undefined>(undefined);

// Custom hook to use the auth context
export const useAuth = () => {
	const context = useContext(AuthContext);
	if (context === undefined) {
		throw new Error("useAuth must be used within an AuthProvider");
	}
	return context;
};

// Provider component that wraps the app and makes auth object available to any child component that calls useAuth()
export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
	const [user, setUser] = useState<User | null>(null);
	const [isLoading, setIsLoading] = useState(true);

	const navigate = useNavigate();

	// Check if user is authenticated on initial load
	useEffect(() => {
		const initializeAuth = async () => {
			try {
				// Try to get current authenticated user from Amplify
				const currentUser = await getCurrentUser();

				if (currentUser) {
					// Get user attributes from Amplify
					const userAttributes = await fetchUserAttributes();

					// Build user object from Amplify attributes
					const userData: User = {
						id: userAttributes.email || "",
						email: userAttributes.email || "",
						firstName: userAttributes.given_name || "",
						lastName: userAttributes.family_name || "",
						country: userAttributes["custom:country"] || "",
						interests: JSON.parse(userAttributes["custom:interests"] || "[]"),
						timezone: userAttributes["custom:timezone"] || "",
						createdAt: userAttributes["custom:created_at"] || "",
					};

					setUser(userData);
				} else {
					setUser(null);
				}
			} catch (error) {
				// User is not authenticated
				setUser(null);
			} finally {
				setIsLoading(false);
			}
		};

		initializeAuth();
	}, []);

	// Add session monitoring to prevent unexpected logouts
	// Session management is handled reactively by apiClient.ts
	// No need for proactive checking - AWS Amplify + reactive refresh handles token lifecycle

	// Check if user is authenticated (Amplify handles token management)
	const isAuthenticated = user !== null;

	// Initiate login with email (starts OTP flow)
	const initiateLogin = async (
		email: string
	): Promise<{ success: boolean; error?: string; session?: string }> => {
		try {
			// Ensure clean state before starting new login
			try {
				await signOut();
			} catch {
				// Ignore errors if no user is signed in
			}

			// Use signIn without password for EMAIL_OTP flow
			const result = await signIn({
				username: email,
				options: {
					authFlowType: "USER_AUTH",
					preferredChallenge: "EMAIL_OTP",
				},
			});

			if (result.nextStep?.signInStep === "CONFIRM_SIGN_IN_WITH_EMAIL_CODE") {
				return {
					success: true,
					session: email,
				};
			}

			return {
				success: false,
				error: "Unexpected authentication flow",
			};
		} catch (error: any) {
			console.error("Login initiation failed:", error);
			return {
				success: false,
				error: error.message || "Login initiation failed",
			};
		}
	};

	// Verify OTP and complete login
	const verifyOTP = async (
		otp: string,
		session?: any
	): Promise<{ success: boolean; error?: string }> => {
		try {
			const result = await confirmSignIn({ challengeResponse: otp });

			// Get user attributes from Amplify
			const userAttributes = await fetchUserAttributes();

			// Create user object from Amplify attributes
			const userData: User = {
				id: userAttributes.email || "",
				email: userAttributes.email || "",
				firstName: userAttributes.given_name || "",
				lastName: userAttributes.family_name || "",
				country: userAttributes["custom:country"] || "",
				interests: JSON.parse(userAttributes["custom:interests"] || "[]"),
				timezone: userAttributes["custom:timezone"] || "",
				createdAt: userAttributes["custom:created_at"] || "",
			};

			// Update React state (Amplify handles token storage)
			setUser(userData);
			navigate("/dashboard");
			return { success: true };
		} catch (error: any) {
			console.error("OTP verification failed:", error);
			return {
				success: false,
				error: error.message || "OTP verification failed",
			};
		}
	};

	// Register new user
	const register = async (
		email: string,
		firstName: string,
		lastName: string,
		country?: string,
		interests?: string[],
		timezone?: string
	): Promise<{ success: boolean; error?: string }> => {
		try {
			// Call backend API which handles both Cognito user creation and database storage
			if (!country || !interests) {
				return { success: false, error: "Country and interests are required" };
			}

			const { apiClient } = await import("@/lib/apiClient");
			await apiClient.register({
				email,
				firstName,
				lastName,
				country,
				interests,
				timezone,
			});

			return { success: true };
		} catch (error: any) {
			console.error("Registration failed:", error);
			return { success: false, error: error.message || "Registration failed" };
		}
	};

	// Verify registration OTP
	const verifyRegistration = async (
		email: string,
		otp: string
	): Promise<{ success: boolean; error?: string }> => {
		try {
			// Confirm the account with the emailed verification code. We do NOT
			// auto-initiate sign-in here — the user is routed to the sign-in page
			// and signs in with a single EMAIL_OTP, avoiding a confusing
			// two-code first-time experience.
			await confirmSignUp({ username: email, confirmationCode: otp });
			return { success: true };
		} catch (error: any) {
			console.error("Registration verification failed:", error);
			return {
				success: false,
				error: error.message || "Registration verification failed",
			};
		}
	};

	// Resend OTP (restart sign-in flow for EMAIL_OTP)
	const resendOTP = async (
		email: string
	): Promise<{ success: boolean; error?: string; session?: string }> => {
		try {
			// For EMAIL_OTP sign-in flow, we need to restart the sign-in process
			// as AWS Amplify doesn't have a direct resend function for sign-in OTP
			const result = await signIn({
				username: email,
				options: {
					authFlowType: "USER_AUTH",
					preferredChallenge: "EMAIL_OTP",
				},
			});

			if (result.nextStep?.signInStep === "CONFIRM_SIGN_IN_WITH_EMAIL_CODE") {
				return { success: true, session: email };
			}

			return { success: false, error: "Failed to resend OTP" };
		} catch (error: any) {
			console.error("Resend OTP failed:", error);
			return { success: false, error: error.message || "Resend OTP failed" };
		}
	};

	// Logout function
	const logout = async () => {
		try {
			await signOut();
		} catch (error) {
			console.error("Logout error:", error);
		} finally {
			// Clear React state (Amplify handles token cleanup)
			setUser(null);
			navigate("/");
		}
	};

	// Update user data (updates both Amplify attributes and local state)
	const updateUser = async (userData: Partial<User>) => {
		if (user) {
			try {
				// Update Amplify user attributes
				const attributesToUpdate: Record<string, string> = {};

				if (userData.firstName !== undefined)
					attributesToUpdate.given_name = userData.firstName;
				if (userData.lastName !== undefined)
					attributesToUpdate.family_name = userData.lastName;
				if (userData.country !== undefined)
					attributesToUpdate["custom:country"] = userData.country;
				if (userData.interests !== undefined)
					attributesToUpdate["custom:interests"] = JSON.stringify(
						userData.interests
					);
				if (userData.timezone !== undefined)
					attributesToUpdate["custom:timezone"] = userData.timezone;

				if (Object.keys(attributesToUpdate).length > 0) {
					const { updateUserAttributes } = await import("aws-amplify/auth");
					await updateUserAttributes({ userAttributes: attributesToUpdate });
				}

				// Update local state
				const updatedUser = { ...user, ...userData };
				setUser(updatedUser);
			} catch (error) {
				console.error("Failed to update user attributes:", error);
				// Still update local state even if Amplify update fails
				const updatedUser = { ...user, ...userData };
				setUser(updatedUser);
			}
		}
	};

	// Get access token (Amplify manages this automatically)
	const getAccessToken = async (): Promise<string | null> => {
		try {
			const session = await fetchAuthSession();
			return session.tokens?.accessToken?.toString() || null;
		} catch (error) {
			return null;
		}
	};

	// Refresh token (force refresh the session)
	const refreshToken = async (): Promise<string | null> => {
		try {
			// Force refresh the session
			const session = await fetchAuthSession({ forceRefresh: true });
			return session.tokens?.accessToken?.toString() || null;
		} catch (error) {
			console.error("Token refresh failed:", error);
			// Don't automatically sign out here, let the caller decide
			return null;
		}
	};

	// Create the value object that will be provided to consumers
	const value: AuthContextType = {
		user,
		isAuthenticated,
		isLoading,
		logout,
		updateUser,
		getAccessToken,
		refreshToken,
		initiateLogin,
		verifyOTP,
		register,
		verifyRegistration,
		resendOTP,
	};

	return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export default AuthContext;
