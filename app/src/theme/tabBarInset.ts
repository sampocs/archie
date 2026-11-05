import { createContext } from "react";

/**
 * How much of the screen's bottom the floating tab bar covers: zero outside the tabs. The tab bar is absolutely
 * positioned (so content blurs beneath it), which means a tab screen must leave this much room to scroll its last row
 * clear of it.
 */
export const TabBarInsetContext = createContext(0);
