import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as React from "react";

import { ScrollRow } from "@/components/ui/scroll-row";
import { useHorizontalOverflow } from "@/hooks/use-horizontal-overflow";
import { cn } from "@/lib/utils";

type TabsVariant = "pills" | "line";

const TabsVariantContext = React.createContext<TabsVariant>("pills");

function Tabs({
  variant = "pills",
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Root> & { variant?: TabsVariant }) {
  return (
    <TabsVariantContext.Provider value={variant}>
      <TabsPrimitive.Root data-slot="tabs" {...props} />
    </TabsVariantContext.Provider>
  );
}

const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, style, ...props }, ref) => {
  const variant = React.useContext(TabsVariantContext);
  const overflow = useHorizontalOverflow<HTMLDivElement>('[data-state="active"]');
  const setOverflowRef = overflow.ref;
  const setRef = React.useCallback(
    (el: HTMLDivElement | null) => {
      setOverflowRef(el);
      if (typeof ref === "function") ref(el);
      else if (ref) ref.current = el;
    },
    [setOverflowRef, ref],
  );
  return (
    <ScrollRow
      overflow={overflow}
      className={cn(
        "gap-1",
        variant === "line" && "w-full shadow-[inset_0_-1px_0_var(--color-border)]",
        className,
      )}
    >
      <TabsPrimitive.List
        ref={setRef}
        style={{ ...overflow.fadeStyle, ...style }}
        className={cn(
          "inline-flex min-w-0 items-center overflow-x-auto text-muted-foreground [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
          variant === "pills" && "h-9 justify-center-safe rounded-lg bg-secondary p-1",
          variant === "line" && "h-9 flex-1 justify-start gap-0 bg-transparent p-0",
        )}
        {...props}
      />
    </ScrollRow>
  );
});
TabsList.displayName = TabsPrimitive.List.displayName;

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => {
  const variant = React.useContext(TabsVariantContext);
  return (
    <TabsPrimitive.Trigger
      ref={ref}
      className={cn(
        "inline-flex shrink-0 items-center justify-center whitespace-nowrap text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
        variant === "pills" &&
          "rounded-md px-3 py-1 hover:text-foreground data-[state=active]:bg-accent data-[state=active]:text-accent-foreground",
        variant === "line" &&
          "rounded-none border-b-2 border-transparent bg-transparent px-3 py-2 shadow-none hover:bg-secondary hover:text-foreground data-[state=active]:border-foreground data-[state=active]:bg-transparent data-[state=active]:text-foreground data-[state=active]:shadow-none",
        className,
      )}
      {...props}
    />
  );
});
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn("mt-4 focus-visible:outline-none", className)}
    {...props}
  />
));
TabsContent.displayName = TabsPrimitive.Content.displayName;

export { Tabs, TabsContent, TabsList, TabsTrigger };
