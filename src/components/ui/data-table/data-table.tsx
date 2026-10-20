import * as React from "react";
import { useTable, flexRender, stockFeatures } from "@tanstack/react-table";
import type {
  ColumnDef,
  ColumnFiltersState,
  ColumnVisibilityState,
  ReactTable,
  RowData,
  RowSelectionState,
  SortingState,
  StockFeatures,
} from "@tanstack/react-table";

import { Input } from "#/components/ui/input.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "#/components/ui/table.tsx";
import { DataTablePagination } from "./data-table-pagination.tsx";
import { DataTableViewOptions } from "./data-table-view-options.tsx";

interface DataTableProps<TData extends RowData> {
  columns: ColumnDef<StockFeatures, TData, any>[];
  data: TData[];
  searchKey?: string;
  searchPlaceholder?: string;
  showViewOptions?: boolean;
  showPagination?: boolean;
  toolbar?: (table: ReactTable<StockFeatures, TData, any>) => React.ReactNode;
}

export function DataTable<TData extends RowData>({
  columns,
  data,
  searchKey,
  searchPlaceholder = "Filter...",
  showViewOptions = true,
  showPagination = true,
  toolbar,
}: DataTableProps<TData>) {
  const [rowSelection, setRowSelection] = React.useState<RowSelectionState>({});
  const [columnVisibility, setColumnVisibility] = React.useState<ColumnVisibilityState>({});
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [sorting, setSorting] = React.useState<SortingState>([]);

  // TanStack Table v9 syntax: useTable with stockFeatures
  const table = useTable({
    data,
    columns,
    features: stockFeatures,
    state: {
      sorting,
      columnVisibility,
      rowSelection,
      columnFilters,
    },
    enableRowSelection: true,
    onRowSelectionChange: setRowSelection,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-1 items-center space-x-2">
          {searchKey && (
            <Input
              placeholder={searchPlaceholder}
              value={(table.getColumn(searchKey)?.getFilterValue() as string) ?? ""}
              onChange={event => table.getColumn(searchKey)?.setFilterValue(event.target.value)}
              className="h-8 w-[150px] lg:w-[250px]"
            />
          )}
          {toolbar?.(table)}
        </div>
        {showViewOptions && <DataTableViewOptions table={table} />}
      </div>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map(headerGroup => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map(header => {
                  return (
                    <TableHead key={header.id} colSpan={header.colSpan}>
                      {header.isPlaceholder
                        ? null
                        : flexRender(header.column.columnDef.header, header.getContext())}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows?.length ? (
              table.getRowModel().rows.map(row => (
                <TableRow key={row.id} data-state={row.getIsSelected() && "selected"}>
                  {row.getVisibleCells().map(cell => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={columns.length} className="h-24 text-center">
                  No results.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      {showPagination && <DataTablePagination table={table} />}
    </div>
  );
}
