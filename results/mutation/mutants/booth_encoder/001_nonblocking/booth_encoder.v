`timescale 1ns/1ps
// 标准答案：取自队友 Booth FPGA 工程 booth_modules.v（未改动）
module cmos_input_inverters(input wire [2:0] bits_in,
    output wire [2:0] inverted);
    // M_INV_B2/B1/B0, interpreted at logic levels, not transistor voltages.
    assign inverted=~bits_in;
endmodule

module memristive_encoder_function(input wire [2:0] b, nb,
    output wire [4:0] decisions);
    wire different=(b[1]&nb[0]) | (nb[1]&b[0]);
    wire p1=nb[2]&different;
    wire n1=b[2]&different;
    wire p2=nb[2]&b[1]&b[0];
    wire n2=b[2]&nb[1]&nb[0];
    wire zero=(nb[2]&nb[1]&nb[0]) | (b[2]&b[1]&b[0]);
    // Functional truth table of G1/G4/G5 encoder. Analog internal nodes omitted.
    assign decisions={n2,p2,n1,p1,zero};
endmodule

module control_restore(input wire window_valid, input wire [4:0] decisions,
    output wire [4:0] gates, complementary_gates);
    // U_RESTORE_* and U_SEL0_RESTORE: resolved Boolean control levels.
    assign gates=window_valid ? decisions : 5'b00001;
    assign complementary_gates=~gates; // M_INV_SEL* complementary controls
endmodule

module booth_encoder(input wire [2:0] bits_in, input wire window_valid,
    output wire [4:0] gates, complementary_gates,
    output reg signed [2:0] digit, output reg [2:0] address);
    wire [2:0] inverted;
    wire [4:0] decisions;
    cmos_input_inverters u_invert(bits_in,inverted);
    memristive_encoder_function u_logic(bits_in,inverted,decisions);
    control_restore u_restore(window_valid,decisions,gates,complementary_gates);
    always @* begin
        case(gates)
            5'b00010: begin digit=1; address=1; end
            5'b00100: begin digit=-1; address=2; end
            5'b01000: begin digit=2; address=3; end
            5'b10000: begin digit=-2; address=4; end
            default: begin digit<=0; address=0; end
        endcase
    end
endmodule
