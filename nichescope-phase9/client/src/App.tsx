import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Route, Switch, useLocation } from "wouter";
import ErrorBoundary from "./components/ErrorBoundary";
import { DashboardLayout } from "./components/dashboard";
import { ThemeProvider } from "./contexts/ThemeContext";
import { SettingsProvider } from "./contexts/SettingsContext";
import {
  AnalyticsPage,
  ErrorsPage,
  NicheDetailPage,
  NichesPage,
  OpportunitiesPage,
  NotFoundPage,
  OverviewPage,
  ProductDetailPage,
  ProductsPage,
  RunDetailPage,
  RunsPage,
  ScraperPage,
  DemandTrackerPage,
  SellerDetailPage,
  SellersPage,
  SchedulesPage,
  LoginPage,
  SettingsPage,
  SystemPage,
} from "./pages/Pages";

function Router() {
  return <Switch>
    <Route path="/login" component={LoginPage} />
    <Route path="/" component={OverviewPage} />
    <Route path="/overview" component={OverviewPage} />
    <Route path="/niches" component={NichesPage} />
    <Route path="/niches/:id" component={NicheDetailPage} />
    <Route path="/opportunities" component={OpportunitiesPage} />
    <Route path="/products" component={ProductsPage} />
    <Route path="/products/:id" component={ProductDetailPage} />
    <Route path="/sellers" component={SellersPage} />
    <Route path="/sellers/:id" component={SellerDetailPage} />
    <Route path="/analytics" component={AnalyticsPage} />
    <Route path="/scraper" component={ScraperPage} />
    <Route path="/demand" component={DemandTrackerPage} />
    <Route path="/runs" component={RunsPage} />
    <Route path="/runs/:id" component={RunDetailPage} />
    <Route path="/schedules" component={SchedulesPage} />
    <Route path="/system" component={SystemPage} />
    <Route path="/errors" component={ErrorsPage} />
    <Route path="/settings" component={SettingsPage} />
    <Route component={NotFoundPage} />
  </Switch>;
}

function AppSurface() {
  const [location] = useLocation();
  return location === "/login" ? <Router /> : <DashboardLayout><Router /></DashboardLayout>;
}

function App() {
  return <ErrorBoundary>
    <ThemeProvider defaultTheme="dark">
      <SettingsProvider><TooltipProvider>
        <Toaster theme="dark" />
        <AppSurface />
      </TooltipProvider></SettingsProvider>
    </ThemeProvider>
  </ErrorBoundary>;
}

export default App;
