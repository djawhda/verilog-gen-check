`timescale 1ns/1ps
// 标准答案：sync_fifo（读写指针多一位区分满/空）
module sync_fifo #(
    parameter integer W = 8,
    parameter integer DEPTH_LOG2 = 4
)(
    input  wire                  clk,
    input  wire                  rst,
    input  wire                  wr_en,
    input  wire [W-1:0]          din,
    input  wire                  rd_en,
    output reg  [W-1:0]          dout,
    output wire                  full,
    output wire                  empty,
    output wire [DEPTH_LOG2:0]   count
);
    localparam integer DEPTH = 1 << DEPTH_LOG2;
    reg [W-1:0]        mem [0:DEPTH-1];
    reg [DEPTH_LOG2:0] wp, rp;

    assign count = wp - rp;
    assign empty = (wp == rp);
    assign full  = (wp[DEPTH_LOG2] != rp[DEPTH_LOG2]) && (wp[DEPTH_LOG2-1:0] == rp[DEPTH_LOG2-1:0]);

    wire do_wr = wr_en && !full;
    wire do_rd = rd_en && !empty;

    always @(posedge clk) begin
        if (rst) begin
            wp   <= {(DEPTH_LOG2+1){1'b0}};
            rp   <= {(DEPTH_LOG2+1){1'b0}};
            dout <= {W{1'b0}};
        end else begin
            if (do_wr) begin
                mem[wp[DEPTH_LOG2-1:0]] <= din;
                wp <= wp + 1'b1;
            end
            if (do_rd) begin
                dout <= mem[rp[DEPTH_LOG2-1:0]];
                rp <= rp + 1'b1;
            end
        end
    end
    assign full = 0;
endmodule
