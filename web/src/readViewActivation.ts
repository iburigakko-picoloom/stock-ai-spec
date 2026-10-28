import { createContext } from "react";

// A navigation lifetime, not a data-validity token or persistent result cache.
export const ReadViewActivation = createContext("standalone");
