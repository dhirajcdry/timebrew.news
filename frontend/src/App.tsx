import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import { lazy, Suspense } from "react";
import Navbar from "./components/common/Navbar";
import Footer from "./components/common/Footer";
import LandingPage from "./components/pages/landing/LandingPage";
import ProtectedRoute from "./components/common/ProtectedRoute";
import { AuthProvider } from "./contexts/AuthContext";

// Keep the public first impression lean; account/dashboard code loads on demand.
const Signup = lazy(() => import("./components/pages/auth/Signup"));
const Login = lazy(() => import("./components/pages/auth/Signin"));
const Dashboard = lazy(() => import("./components/pages/dashboard/Dashboard"));
const CreateBrew = lazy(() => import("./components/pages/dashboard/CreateBrew"));
const BrewDetails = lazy(() => import("./components/pages/dashboard/BrewDetails"));

const App = () => {
	return (
		<Router>
			<AuthProvider>
				<div className="min-h-screen flex flex-col bg-gradient-to-br from-background via-card to-muted text-foreground">
				<Navbar />
				<main className="flex-1">
						<Suspense fallback={<p role="status" className="px-6 py-32 text-center">Loading your next page…</p>}>
					<Routes>
						{/* Public Routes */}
						<Route path="/" element={<LandingPage />} />
						<Route path="/signup" element={<Signup />} />
						<Route path="/signin" element={<Login />} />

						{/* Protected Routes */}
						<Route element={<ProtectedRoute />}>
							<Route path="/dashboard" element={<Dashboard />} />
							<Route path="/dashboard/create-brew" element={<CreateBrew />} />
							<Route path="/dashboard/brew/:id" element={<BrewDetails />} />
							{/* Add more protected routes here */}
						</Route>
					</Routes>
						</Suspense>
				</main>
				<Footer />
			</div>
			</AuthProvider>
		</Router>
	);
};

export default App;
