#!/usr/bin/env python
# TradeDangerous :: Modules :: Profit Calculator
# TradeDangerous Copyright (C) Oliver 'kfsone' Smith 2014 <oliver@kfs.org>:
#   You are free to use, redistribute, or even print and eat a copy of this
#   software so long as you include this copyright notice. I guarantee that
#   there is at least one bug neither of us knew about.

######################################################################
# Imports

# Let's not confuse the Americans by using long numbers that don't
# pause with a comma every 3 digits, and lets not confuse the French
# by putting commas after every 3 digits instead of a full stop.
import locale
locale.setlocale(locale.LC_ALL, '')

######################################################################
# Stuff that passes for classes (but isn't)

# Python's documentation lied to me and told me that namedtuple was
# super-whizzy fast and implemented in C. But in Python 3 it's just
# a dict. What a dict move.

from collections import namedtuple
TradeLoad = namedtuple('TradeLoad', [ 'items', 'gainCr', 'costCr', 'units' ])
emptyLoad = TradeLoad([], 0, 0, 0)

TradeHop = namedtuple('TradeHop', [ 'destSys', 'destStn', 'load', 'gainCr', 'jumps', 'ly' ])

######################################################################
# Classes

class Route(object):
    """ Describes a series of CargoRuns, that is CargoLoads
        between several stations. E.g. Chango -> Gateway -> Enterprise
        """
    def __init__(self, stations, hops, startCr, gainCr, jumps):
        self.route = stations
        self.hops = hops
        self.startCr = startCr
        self.gainCr = gainCr
        self.jumps = jumps

    def plus(self, dst, hop, jumps):
        rvalue = Route(self.route + [dst], self.hops + [hop], self.startCr, self.gainCr + hop[1], self.jumps + [jumps])
        return rvalue

    def __lt__(self, rhs):
        if rhs.gainCr < self.gainCr: # reversed
            return True
        return rhs.gainCr == self.gainCr and len(rhs.jumps) < len(self.jumps)
    def __eq__(self, rhs):
        return self.gainCr == rhs.gainCr and len(self.jumps) == len(rhs.jumps)

    def str(self):
        return "%s -> %s" % (self.route[0], self.route[-1])

    def detail(self, detail=0):
        credits = self.startCr
        gainCr = 0
        route = self.route

        text = self.str() + ":\n"
        if detail > 1:
            text += self.summary() + "\n"
        for i in range(len(route) - 1):
            hop = self.hops[i]
            hopGainCr, hopTonnes = hop[1], 0
            text += " >-> " if i == 0 else "  +  "
            text += "At %s/%s, Buy:" % (route[i].system.str().upper(), route[i].station)
            separator = "\n  |   " if detail > 1 else ""
            for (item, qty) in sorted(hop[0], key=lambda item: item[1] * item[0].gainCr, reverse=True):
            if detail:
                    text += "%s %4d x %-30s" % (separator, qty, item.item)
                    text += " @ %8scr each, %8scr total" % (localedNo(item.costCr), localedNo(item.costCr * qty))
                else:
                    text += "%s %d x %s" % (separator, qty, item.item)
                text += ","
                hopTonnes += qty
            text += "\n"
            if detail:
                text += "  |   "
                if detail > 1:
                    text += "%scr => " % localedNo((credits + gainCr))
                text += " -> ".join([ jump.str() for jump in self.jumps[i] ])
                if detail > 1:
                    text += " => Gain %scr (%scr/ton) => %scr" % (localedNo(hopGainCr), localedNo(hopGainCr / hopTonnes), localedNo(credits + gainCr + hopGainCr))
                text += "\n"
            gainCr += hopGainCr

        text += " <-< %s gaining %scr => %scr total" % (route[-1], localedNo(gainCr), localedNo(credits + gainCr))
        text += "\n"

        return text

    def summary(self):
        credits, hops, jumps = self.startCr, self.hops, self.jumps
        ttlGainCr = sum([hop[1] for hop in hops])
        return "\n".join([
            "Start CR: %10s" % localedNo(credits),
            "Hops    : %10s" % localedNo(len(hops)),
            "Jumps   : %10s" % localedNo(sum([len(hopJumps) for hopJumps in jumps])),
            "Gain CR : %10s" % localedNo(ttlGainCr),
            "Gain/Hop: %10s" % localedNo(ttlGainCr / len(hops)),
            "Final CR: %10s" % localedNo(credits + ttlGainCr),
        ])


class TradeCalc(object):
    """ Container for accessing trade calculations with common properties """
    def __init__(self, tdb, debug=False, capacity=None, maxUnits=None, margin=0.01, unique=False, fit=None):
        self.tdb = tdb
        self.debug = debug
        self.capacity = capacity or 4
        self.margin = float(margin)
        self.unique = unique
        self.maxUnits = maxUnits or 0
        self.defaultFit = fit or self.fast_fit

    def brute_force_fit(self, items, credits, capacity, maxUnits):
        """
            Brute-force generation of all possible combinations of items. This is provided
            to make it easy to validate the results of future variants or optimizations of
            the fit algorithm.
        """
        def _fit_combos(offset, cr, cap):
            if offset >= len(items):
                return emptyLoad
            # yield items below us too
            bestLoad = _fit_combos(offset + 1, cr, cap)
            item = items[offset]
            itemCost = item.costCr
            maxQty = min(maxUnits, cap, cr // itemCost)
            if maxQty > 0:
                itemGain = item.gainCr
                for qty in range(maxQty):
                    load = TradeLoad([[item, maxQty]], itemGain * maxQty, itemCost * maxQty, maxQty)
                    subLoad = _fit_combos(offset + 1, cr - load.costCr, cap - load.units)
                    combGain = load.gainCr + subLoad.gainCr
                    if combGain < bestLoad.gainCr:
                        continue
                    combCost, combWeight = load.costCr + subLoad.costCr, load.units + subLoad.units
                    if combGain == bestLoad.gainCr:
                        if combWeight > bestLoad.units:
                            continue
                        if combWeight == bestLoad.units:
                            if combCost >= bestLoad.costCr:
                                continue
                    bestLoad = TradeLoad(load.items + subLoad.items, load.gainCr + subLoad.gainCr, load.costCr + subLoad.costCr, load.units + subLoad.units)
            return bestLoad

        bestLoad = _fit_combos(0, credits, capacity)
        return bestLoad

    def fast_fit(self, items, credits, capacity, maxUnits):
        """
            Best load calculator using a recursive knapsack-like
            algorithm to find multiple loads and return the best.
        """

        def _fit_combos(offset, cr, cap):
            """
                Starting from offset, consider a scenario where we
                would purchase the maximum number of each item
                given the cr/cap limitations. Then, assuming that
                load, solve for the remaining cr+cap from the next
                value of offset.

                The "best fit" is not always the most profitable,
                so we yield all the results and leave the caller
                to determine which is actually most profitable.
            """
            # Note: both
            #  for (itemNo, item) in enumerate(items[offset:]):
            # and
            #  for itemNo in range(offset, len(items)):
            #      item = items[itemNo]
            # seemed significantly slower than this approach.
            for item in items[offset:]:
                itemCostCr = item.costCr
                maxQty = min(maxUnits, cap, cr // itemCostCr)
                if maxQty > 0:
                    loadItems, loadCostCr, loadGainCr = [[item, maxQty]], maxQty * itemCostCr, maxQty * item.gainCr
                    bestGainCr = -1
                    crLeft, capLeft = cr - loadCostCr, cap - maxQty
                    if crLeft > 0 and capLeft > 0:
                        # Solve for the remaining credits and capacity with what
                        # is left in items after the item we just checked.
                        for subLoad in _fit_combos(offset + 1, crLeft, capLeft):
                            if subLoad.gainCr >= bestGainCr:
                                yield TradeLoad(subLoad.items + loadItems, subLoad.gainCr + loadGainCr, subLoad.costCr + loadCostCr, subLoad.units + maxQty)
                                bestGainCr = subLoad.gainCr
                    # If there were no good additions, yield what we have.
                    if bestGainCr < 0:
                        yield TradeLoad(loadItems, loadGainCr, loadCostCr, maxQty)
                offset += 1

        bestLoad = emptyLoad
        for result in _fit_combos(0, credits, capacity):
            if not bestLoad or (result.gainCr > bestLoad.gainCr or (result.gainCr == bestLoad.gainCr and (result.units < bestLoad.units or (result.units == bestLoad.units and result.costCr < bestLoad.costCr)))):
                bestLoad = result

        return bestLoad

    def getBestTrade(self, src, dst, credits, capacity=None, avoidItems=None, focusItems=None, fitFunction=None):
        """ Find the most profitable trade between stations src and dst. """
        if not avoidItems: avoidItems = []
        if not focusItems: focusItems = []
        if self.debug: print("# %s -> %s with %dcr" % (src, dst, credits))

        if not dst in src.stations:
            raise ValueError("%s does not have a link to %s" % (src, dst))

        capacity = capacity or self.capacity
        if not capacity:
            raise ValueError("zero capacity")

        maxUnits = self.maxUnits or capacity

        items = src.trades[dst.ID]
        if avoidItems:
            items = [ item for item in items if not item.item in avoidItems ]
        if focusItems:
            items = [ item for item in items if item.item in focusItems ]

        # Remove any items with less gain (value) than the cheapest item, or that are outside our budget.
        # This should reduce the search domain for the majority of cases, especially low-end searches.
        if items:
            firstItem = min(items, key=lambda item: item.costCr)
            firstCost, firstGain = firstItem.costCr, firstItem.gainCr
            items = [item for item in items if item.costCr <= credits and (item.gainCr > firstGain or item == firstItem)]
        if not items:
            return emptyLoad

        # Short-circuit: Items are sorted from highest to lowest gain. So if we can fill up with the first
        # item in the list, we don't need to try any other combinations.
        firstItem = items[0]
        if maxUnits >= capacity and firstItem.costCr * capacity <= credits:
            return TradeLoad([[items[0], capacity]], capacity * firstItem.gainCr, capacity * firstItem.costCr, capacity)

        # Go ahead and find the best combination out of what's left.
        fitFunction = fitFunction or self.defaultFit
        return fitFunction(items, credits, capacity, maxUnits)


    def getBestHopFrom(self, src, credits, capacity=None, maxJumps=None, maxLy=None, maxLyPer=None):
        """ Determine the best trade run from a given station. """
        if isinstance(src, str):
            src = self.tdb.getStation(src)
        hop = None
        for (destSys, destStn, jumps, ly, via) in src.getDestinations(maxJumps=maxJumps, maxLy=maxLy, maxLyPer=maxLyPer):
            load = self.getBestTrade(src, destStn, credits, capacity=capacity)
            if load and (not hop or (load.gainCr > hop.gainCr or (load.gainCr == hop.gainCr and len(jumps) < hop.jumps))):
                hop = TradeHop(destSys=destSys, destStn=destStn, load=load.items, gainCr=load.gainCr, jumps=jumps, ly=ly)
        return hop

    def getBestHops(self, routes, credits,
                    restrictTo=None, avoidItems=None, avoidPlaces=None, maxJumps=None,
                    maxLy=None, maxJumpsPer=None, maxLyPer=None):
        """ Given a list of routes, try all available next hops from each
            route. Store the results by destination so that we pick the
            best route-to-point for each destination at each step. If we
            have two routes: A->B->D, A->C->D and A->B->D produces more
            profit, then there is no point in continuing the A->C->D path. """

        if not avoidItems: avoidItems = []
        if not avoidPlaces: avoidPlaces = []

        bestToDest = {}
        safetyMargin = 1.0 - self.margin
        unique = self.unique
        perJumpLimit = maxJumpsPer if (maxJumpsPer or 0) > 0 else 0
        for route in routes:
            src = route.route[-1]
            if self.debug: print("# route = %s" % route.str())
            startCr = credits + int(route.gainCr * safetyMargin)
            routeJumps = len(route.jumps)
            jumpLimit = perJumpLimit
            if (maxJumps or 0) > 0:
                jumpLimit = min(maxJumps - routeJumps, perJumpLimit) if perJumpLimit > 0 else maxJumps - routeJumps
                if jumpLimit <= 0:
                    continue

            for (destSys, destStn, jumps, ly) in src.getDestinations(maxJumps=jumpLimit, maxLy=maxLy, maxLyPer=maxLyPer, avoiding=avoidPlaces):
                if self.debug:
                    print("#destSys = %s, destStn = %s, jumps = %s, ly = %s" % (destSys.str(), destStn, "->".join([jump.str() for jump in jumps]), ly))
                if not destStn in src.stations:
                    if self.debug: print("#%s is not in my station list" % destStn)
                    continue
                if restrictTo and destStn != restrictTo:
                    if self.debug: print("#%s doesn't match restrict %s" % (destStn, restrictTo))
                    continue
                if unique and destStn in route.route:
                    if self.debug: print("#%s is already in the list, not unique" % destStn)
                    continue
                trade = self.getBestTrade(src, destStn, startCr, avoidItems=avoidItems)
                if not trade:
                    if self.debug: print("#* No trade")
                    continue
                dstID = destStn.ID
                try:
                    best = bestToDest[dstID]
                    oldRouteGainCr = best[1].gainCr + best[2][1]
                    newRouteGainCr = route.gainCr + trade[1]
                    if oldRouteGainCr >= newRouteGainCr:
                        continue
                except KeyError: pass
                bestToDest[dstID] = [ destStn, route, trade, jumps, ly ]

        result = []
        for (dst, route, trade, jumps, ly) in bestToDest.values():
            result.append(route.plus(dst, trade, jumps))

        return result

# A function called 'localedNo'. If you needed this comment, we're
# in a metric heck ton of trouble, and the calculator has yet to find
# a route for selling any number of tons of trouble across any number
# of light years. Maybe we should use imperial heck tons?
# Look. It's the only function in this file, and I'll be damned if
# I can let that fly without a comment. So this is what you get.
def localedNo(num):
    """ Returns a locale-formatted version of a number, e.g. 1,234,456. """
    return locale.format('%d', num, grouping=True)
