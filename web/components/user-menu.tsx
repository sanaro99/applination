"use client";

import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Compass, LogOut, User as UserIcon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { api } from "@/lib/api";
import { useTourLauncher } from "@/components/tour/tour-root";

export function UserMenu() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const startTour = useTourLauncher();

  const { data: user } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.me(),
    retry: false,
    staleTime: 5 * 60_000,
  });

  const logout = useMutation({
    mutationFn: () => api.logout(),
    onSuccess: () => {
      // Clear everything: the next account must not see cached rows from this
      // one, even for the moment before their own queries resolve.
      queryClient.clear();
      router.replace("/login");
    },
    onError: () => toast.error("Could not sign out"),
  });

  if (!user) return null;

  return (
    <DropdownMenu>
      {/* base-ui composes via `render`, not Radix's `asChild`. */}
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            className="size-8 text-muted-foreground hover:text-foreground"
            aria-label="Account"
          />
        }
      >
        <UserIcon className="size-4" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="font-normal">
            <span className="block truncate text-sm">{user.email}</span>
            {user.is_owner && (
              <span className="text-xs text-muted-foreground">Owner</span>
            )}
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        {/* This menu is base-ui's Menu.Item, not Radix — it only fires
            `onClick`, not `onSelect`. */}
        <DropdownMenuItem onClick={startTour}>
          <Compass className="mr-2 size-4" />
          Take the tour
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onClick={() => logout.mutate()}
          disabled={logout.isPending}
        >
          <LogOut className="mr-2 size-4" />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
